# Aurora cluster topology: ingest is writer-bound, offloading reads, and whether ord-app needs its own instance

- **Date:** 2026-07-01
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** aws, aurora, cost, database, ingest, topology

## Question

The full-ORD ingest benchmark (16-worker sharded COPY loader, ord-schema #879)
ran far slower than the local benchmarks predicted. Why? And what cluster
topology gives us fast bulk ingest, good steady-state search reads, and
reasonable cost? Three concrete sub-questions:

1. Do our clients use a reader endpoint today?
2. Can we run a Serverless v2 writer that scales toward zero alongside a
   right-sized reader (mixing serverless and provisioned instances)?
3. Does ord-app's more-frequent write load justify its own RDS instance?

## Summary

- **The ingest bottleneck is the shared 2-vCPU writer (`db.t4g.large`), not the
  client.** During the run the writer sat at **87–93% CPU** with **commit
  latency 55–90 ms** while the 16-vCPU dev VM was **96% idle** (load 1.68/16,
  16 of 17 Python workers sleeping). All writes funnel through the single
  writer, so client-side parallelism (#879 sharding, `n_jobs`) cannot help.
  Client memory was a non-issue (~4 GiB of 30; ~0.24 GB/worker).
- **We do not use a reader endpoint.** Search reads, editor writes, and ord-app
  all connect to the single cluster (writer) endpoint
  (`POSTGRES_HOST = rds_endpoint = cluster.endpoint`). No reader instances
  exist; there is no read/write split.
- **`db.t4g.large` is still correct for steady-state reads** (per
  [2026-06-24](2026-06-24-aurora-io-optimized-storage-mode.md): chosen to cache
  the ~2.5 GB working set and collapse read I/O). The ingest problem is a
  *transient write-load* problem, not a steady-state sizing error — and
  serverless-pinned-at-1-ACU is the regime we deliberately left, not one to
  repeat.
- **Target topology (client change agreed):** a right-sized reader serving
  search (warm cache) + a Serverless v2 writer (min ~0.5, max ~16–32 ACU) that
  auto-scales up for ingest, with clients split reads→reader / writes→writer.
  The real win is **auto-scaling ingest with no manual resize or maintenance
  window** — not scale-to-zero.
- **Don't chase scale-to-zero, and don't give ord-app its own instance yet.**
  ord-app's frequent writes keep the writer awake, so true $0-idle won't happen
  regardless; a modest min ACU is cheap. Isolating ord-app costs roughly what
  the enabled idle-savings would recover (~$40–50/mo either way) while adding an
  instance to run, patch, back up, secure, and connect to. Not justified at
  current scale — revisit on the triggers below.

## Method

- **Benchmark run:** 2026-07-01, dev VM `i-080fa23d58cf7e813` (c8i.4xlarge,
  16 vCPU / 30 GiB), sharded COPY loader on ord-schema `main` (#877 COPY, #879
  row-group sharding, #881 partial FK indexes), `n_jobs=16`, streaming all 53
  parquet datasets (~2.4M reactions) into a fresh DB `ord_20260630` on prod
  cluster `cluster` (account `482491871729`, `us-east-1`).
- **Writer metrics:** `aws cloudwatch get-metric-statistics` for
  `cluster-instance-0` over the run window — `CPUUtilization`, `CommitLatency`,
  `WriteIOPS`, `DatabaseConnections`, `CPUCreditBalance`, `FreeableMemory`.
- **Client:** `uptime`, `mpstat`, `ps` process states, and `public.reactions`
  count deltas over the SSM session.
- **Endpoint wiring:** traced `POSTGRES_HOST` / `ORD_INTERFACE_POSTGRES` in
  ord-interface and `rds_endpoint` / `cluster.endpoint` in ord-infrastructure.
- **Config:** `describe-db-clusters`, `describe-db-instances`.

## Findings

### The writer is the wall

Writer is `db.t4g.large` — 2 vCPU, 8 GiB, Graviton **burstable**.

| Metric (writer, during run) | Value | Read |
|---|---|---|
| CPUUtilization | 87–93% sustained | CPU-saturated |
| CommitLatency | 55–90 ms (from ~22 ms) | commits queuing (healthy is single-digit ms) |
| WriteIOPS | ramped to ~100,000 | heavy index/FK write amplification |
| DatabaseConnections | 25 | 16 workers + prep/finalize — fine |
| CPUCreditBalance | ~864→848, stable | **not** credit-throttled — it's the raw 2-vCPU ceiling |
| FreeableMemory | ~0.7 GB of 8 GiB | tight, not the wall |

Client side: load average 1.68 on 16 cores, 16/17 Python processes in `S`
(sleeping on the DB socket), CPU ~96% idle. A 16-vCPU client feeding a 2-vCPU
database is a firehose into a straw.

### Aurora architecture recap — why a reader cannot fix ingest

Aurora separates compute (instances) from storage (one distributed volume,
6-way replicated across 3 AZs, shared by every instance). A cluster has exactly
**one writer** plus **0–15 readers**, all on the same storage. **All writes go
through the writer**; readers are read-only near-real-time replicas. So a bigger
reader helps *reads*, never *writes/ingest*. Adding a reader duplicates no
storage (near-instant, compute-only cost).

### No reader endpoint today

- Search API connects with `host=os.environ["POSTGRES_HOST"]`
  (`ord_interface/api/search.py`); the editor uses the same `POSTGRES_HOST`
  (`ord_interface/editor/py/serve.py`).
- In prod, `POSTGRES_HOST = rds_endpoint = cluster.endpoint` — the **writer**
  endpoint (`ord-infrastructure` `stacks/backend/__main__.py`,
  `stacks/interface/__main__.py`). No `readerEndpoint` is exported or
  referenced, and there are no reader instances.
- Consequence: read-heavy search and the write paths share one endpoint (one
  env var). Offloading reads therefore needs a real read/write split, not a
  single repoint.

### Serverless writer + right-sized reader

Mixing `db.serverless` (Serverless v2) and provisioned instances in one cluster
is supported, and role (writer/reader) is independent of class. Serverless v2
can scale to **0 ACU** (auto-pause); the cluster already carries
`ServerlessV2ScalingConfiguration {min 0.0, max 1.0}`, inert while the instance
is provisioned. The design: a warm provisioned reader serves search; a
serverless writer auto-scales up for ingest and down when idle. Caveats:

- **Requires the read/write split** — reads to the reader endpoint, writes to
  the writer. Without it, reads hit the serverless writer and eat resume
  latency, a cold cache, and storage I/O whenever it scales down (the exact
  2026-06-24 problem). Steven is willing to fix the clients for this.
- **Raise max ACU** from 1.0 to ~16–32; otherwise the serverless writer is as
  underpowered as the t4g.large.
- **Resume latency:** first write after an idle-pause takes seconds to wake —
  fine for a batch/submission pattern, noticeable for interactive writes.
- **Validate scale-to-0 with an always-on reader** present — auto-pause
  historically wants cluster-wide idle; the writer-pauses-while-reader-serves
  interaction should be confirmed before betting on $0 idle.
- **Set failover tiers** so a writer failure promotes the intended instance.
- **Migration path** (can't add a second writer directly): add a serverless
  reader → failover to promote it (t4g.large demotes to reader) → set min/max.
  One ~30 s failover.

### ord-app: dedicated instance?

ord-app writes are "fairly common," which conflicts with a scale-to-zero writer.
The economics, at current scale (rough, us-east-1):

- Keep ord-app shared: its writes keep the writer lightly awake, so it runs at a
  modest min (~0.5–1 ACU ≈ $44–88/mo) instead of pausing. No extra instance.
- Separate ord-app: the main writer can now idle (~$0–15/mo), but you add a
  dedicated instance (~$44–52/mo for a small serverless/`t4g.medium`). Net is
  roughly a **wash**, and you take on a second instance to run, patch, back up,
  secure, and point clients at.

So separating ord-app *purely to unlock writer scale-to-zero* is not
cost-justified, and it adds operational surface. **Keep ord-app on the shared
cluster; don't rely on scale-to-zero.** Revisit isolation when a real driver
appears:

- ord-app write throughput grows enough to contend with search or ingest on the
  shared writer;
- ord-app needs independent availability, backup cadence, or maintenance windows
  (so a shared-writer reboot/failover can't couple it to ORD work); or
- compliance requires physical data isolation.

To verify before any split: ord-app's actual write QPS, and whether it reads ORD
search data (cross-database coupling would complicate separation).

## Conclusions / next steps

1. **Read/write split (agreed).** Export `cluster.readerEndpoint` from
   ord-infrastructure and give read-only search clients a reader host var; keep
   editor/app writes on the writer endpoint. (The editor is slated for deletion
   ~Aug 2026 and is off-limits until then; search and app can move now.)
2. **Reader + serverless writer.** Add a right-sized reader; migrate to a
   Serverless v2 writer (min ~0.5, max ~16–32) via add-reader→failover, keeping
   `db.t4g.large` as the warm search reader.
3. **ord-app stays shared;** set the writer's min ACU modestly rather than
   chasing $0 idle.
4. **Immediate fast-ingest measurement is independent of all this:** run it on a
   separate throwaway cluster (which also avoids polluting the ~2026-07-01
   steady-state I/O measurement scheduled in the 2026-06-24 entry), or
   temporarily scale the writer up in a maintenance window.

## References

- Prod account `482491871729`, `us-east-1`, cluster `cluster`, writer
  `cluster-instance-0` (`db.t4g.large`, 2 vCPU / 8 GiB).
- ord-schema ingest work: #877 (COPY loader), #879 (row-group sharding), #881
  (partial FK indexes), #878 (further-speedups, closed).
- Prior entry: [2026-06-24 Aurora storage mode / serverless→provisioned
  migration](2026-06-24-aurora-io-optimized-storage-mode.md).
- ord-interface: `ord_interface/api/search.py`,
  `ord_interface/editor/py/serve.py` (both use `POSTGRES_HOST`).
- ord-infrastructure: `stacks/backend/__main__.py`
  (`rds_endpoint = cluster.endpoint`), `stacks/interface/__main__.py`,
  `stacks/app/__main__.py`.
- AWS: Aurora Serverless v2 scaling (min 0 ACU / auto-pause), mixed
  provisioned + serverless clusters, cluster vs reader endpoints.
