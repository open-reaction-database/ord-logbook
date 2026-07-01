# Ingest & derivation performance: a 2.4M-reaction load should not take a day

- **Date:** 2026-06-30
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** performance, ingest, orm, database, aurora, cost

## Question

A full production population of the ORM database (`ord_20260629` on the prod Aurora cluster) ran for ~24h+ to load 2.4M reactions and was still in the derivation stage. 2.4M reactions is not a large corpus. Why is it so slow, can we get a full rebuild down to ~2h, and is optimizing it worth the money?

## Summary

**It's an implementation problem, not a data-volume problem — and the money is a non-issue, so the driver for fixing it is wall-clock/operational, not cost.**

- Ingest runs at **~64 reactions/sec** because it loads through the SQLAlchemy ORM unit of work — one reaction becomes a tree of ~30 Python objects, so 2.4M reactions is ~73M objects constructed and flushed. The CPU is entirely in Python object churn; Postgres is idle.
- Derivation is worse: the compound-SMILES pass does one `session.get()` + lazy child-load **per compound**, ~8M times — millions of latency-bound round-trips, ~13h for the big dataset alone.
- **Cost of the whole run: ~$10.** Aurora billed ~34.3M I/O over the 30h window (~$6.90 at $0.20/1M); the `db.t4g.large` instance runs 24/7 regardless (sunk); storage is negligible. Read I/O was *low* (12M) because the working set is cached — so the slow derive costs latency, not dollars. **Do not optimize to save RDS money.**
- The fix is to stop using the ORM for bulk work: **`COPY`-based ingest** and **set-based compound derivation**. Target: a full rebuild in **~1h or less**.
- Filed as [ord-schema#872](https://github.com/open-reaction-database/ord-schema/issues/872) (derive, smaller/safer, do first) and [ord-schema#873](https://github.com/open-reaction-database/ord-schema/issues/873) (COPY ingest, prototype-gated).
- **Progress:** the derive fix is implemented in [ord-schema#874](https://github.com/open-reaction-database/ord-schema/pull/874) (set-based, value-parity tested). Profiling of the ingest loop (below) confirms flush dominates (66%) and bounds the COPY win at ~3–10×.

## Method

Measured against the live production population run:

- **Host:** dev-vm `i-080fa23d58cf7e813` (`x8i.large`, 2 vCPU) → prod Aurora PostgreSQL cluster `cluster`, instance `cluster-instance-0` (`db.t4g.large`, 2 vCPU / 8 GB, single-AZ, Aurora Standard storage), in-VPC.
- **Command:** `ord_schema.orm.scripts.add_datasets --stages ingest,derived --classify_reactions --n_jobs 1` over all 53 local `ord-data` parquet files, in tmux.
- **Rates/progress:** the ingest/derive `tqdm` bars in the run log, sampled over the run.
- **Row counts:** `psycopg` queries against `public.datasets`, `ord.reaction`, `derived.*`.
- **Cost:** `aws cloudwatch get-metric-statistics` for `VolumeReadIOPs`/`VolumeWriteIOPs` (Sum, 30h window) × Aurora Standard $0.20 per 1M I/O; instance/storage from `describe-db-instances` / `describe-db-clusters`.
- **Root cause:** inspection of `ord_schema/orm/database.py` at commit `1d358ba`.

## Findings

### The live run

- **53 datasets, 2,428,291 reactions** ingested and committed.
- The population is dominated by one dataset, `ord_dataset-1158e351757f315b93cbcbe7bc55f38e` (**1,771,032 reactions**); a second (`e7830cd6…`, 409k) and a handful of 30–50k datasets make up most of the rest.
- **Ingest:** the big dataset took **~8h11m** at a sustained **~64 rxn/s**; total ingest across all 53 was ~11h.
- **Derivation:** the big dataset's `compound_smiles` pass is ~8,068 batches of 1,000 (~8M compounds) at **~7.1 s/batch (~7 ms/compound)** — ~13h+ elapsed and still running at last check. Reaction-class assignment (Rxn-INSIGHT, fingerprint-based) is comparatively cheap.
- **Memory stayed flat at ~2.6–3.0 GB RSS** throughout — the batched-derive change ([ord-schema#864](https://github.com/open-reaction-database/ord-schema/pull/864)) does bound the footprint; that goal was met. Slowness is orthogonal to memory.

### Root cause — ORM row-by-row, not the data

Ingest, `add_parquet_dataset` (`ord_schema/orm/database.py:280`):

```python
for _, reaction in tqdm(parquet.iter_reactions(path), ...):
    reaction_mapper = from_proto(reaction, mapper=reaction_child_class)  # ~30 ORM objects/reaction
    session.add(reaction_mapper)
    if len(pending) >= _PARQUET_FLUSH_BATCH:
        session.flush()
```

Derivation, `_update_compound_smiles` (`ord_schema/orm/database.py:475`):

```python
for compound_id in compound_ids[batch_start : batch_start + _DERIVED_BATCH]:
    compound = session.get(compound_class, compound_id)     # 1 round-trip
    smiles = smiles_from_compound(to_proto(compound))        # lazy child loads -> more round-trips
```

The reaction-SMILES pass was rewritten in #864 to bulk-fetch serialized protos per batch; the compound pass never got the same treatment.

### Cost

| Item | Amount |
|------|--------|
| Aurora billed write I/O (30h) | 22,172,803 |
| Aurora billed read I/O (30h) | 12,111,293 |
| Total I/O × $0.20/1M | **~$6.90** |
| `db.t4g.large` instance | sunk (runs 24/7) |
| dev-vm EC2 | a few $ |
| **Marginal cost of the run** | **~$10, one-time** |

Read I/O is low relative to ~8M per-compound fetches because most reads hit Aurora's buffer cache and aren't billed — reinforcing that the derive bottleneck is **round-trip latency, not I/O**.

### Ingest profile (2026-06-30 update)

Profiled the ORM ingest loop on 2,000 reactions of `ord_dataset-805ad863…` against a local Postgres over a **unix socket** (network eliminated), `_PARQUET_FLUSH_BATCH`-style flushes of 200:

- **49.8 rxn/s** — matching prod's ~64, confirming the bottleneck is client/CPU, not the DB or network.
- **flush: 66%** (`session.flush` → INSERT emission). The tell: **20,360 SQL executes for 2,000 reactions (~10 per reaction)** — the unit of work is not collapsing the ~30 child rows/reaction into set inserts; `_emit_insert_statements` alone is 12s.
- **from_proto (ORM object construction): 26%** (289,982 recursive calls for 2,000 reactions).
- other: 8%.

Bounding the COPY win: replacing flush alone (keeping `from_proto`) removes most of the 66% → ~3×; additionally walking the proto straight to per-table tuples (skipping `from_proto`) attacks the 26% → toward ~10×.

### COPY loader prototype (2026-06-30)

Built a prototype that reuses `from_proto` (so the proto→columns mapping stays consistent with the generated schema), assigns UUIDv7 ids and wires foreign keys from the ORM relationship metadata, and streams rows with psycopg `COPY` per table (in `Base.metadata.sorted_tables` order for FK dependencies) instead of the unit of work.

- **Speed: 210 rxn/s vs. the ORM's ~45 → 4.3×**, single-threaded, still including `from_proto`. Big dataset ~8h → ~1.9h on this basis; parallelism (existing `n_jobs` across datasets) and a `from_proto` bypass are additive on top.
- **Correctness: byte-identical to the ORM.** A parity harness ingests the same reactions both ways into separate databases and compares, per table, an order-independent digest of every non-id/non-FK column: **parity across all 39 non-empty tables**. (Two gotchas surfaced and were handled: sibling-subclass FK columns on shared polymorphic tables are NULL for a given instance; and `set_submitted_at` must run after load, as the ORM path does.)
- Confirmed on the uuidv7 branch that #875 alone does **not** speed the ORM path (flush still 68%) — it is purely the COPY enabler.

## Conclusions / next steps

The ORM is the right tool for serving/reading; it is the wrong tool for bulk loading. The read path confirms this: ord-interface queries the tables in raw SQL (`FROM ord.reaction …`), so the ORM *object* layer is used almost only by `from_proto` (ingest) and a now-minor `to_proto` (compound-derive fallback). Nothing reads through the ORM, so bypassing it for ingest costs no read-path behavior. Plan, highest-leverage first:

1. **Set-based compound-SMILES derive** ([ord-schema#872](https://github.com/open-reaction-database/ord-schema/issues/872)) — pull SMILES from `ord.compound_identifier` in one SQL pass, RDKit-fallback only for compounds without a SMILES identifier. **Done: [ord-schema#874](https://github.com/open-reaction-database/ord-schema/pull/874)** (value-parity tested).
2. **UUIDv7 surrogate keys** ([ord-schema#857](https://github.com/open-reaction-database/ord-schema/issues/857)) — the enabler for COPY. Client-generatable + time-sortable ids remove the one hard part of a COPY loader (client-side PK assignment for FK wiring); integer serial ids would force sequence-block reservation or per-row round-trips. UUIDv7 over ULID: same time-sortability, but native `uuid` type and standard tooling for what are internal-only keys. **Done: [ord-schema#875](https://github.com/open-reaction-database/ord-schema/pull/875)** (`rdkit.*` stays integer serial — server-populated; `public.*` keyed on business strings; reads unaffected).
3. **`COPY`-based ingest** ([ord-schema#873](https://github.com/open-reaction-database/ord-schema/issues/873)) — build the trees, mint UUIDv7 ids, wire FKs from relationship metadata, and stream rows per table via psycopg `COPY`. **Done: [ord-schema#877](https://github.com/open-reaction-database/ord-schema/pull/877)** — 4.3× (210 vs 45 rxn/s), byte-parity with the ORM path. Remaining headroom (measured follow-ups): bypass `from_proto` (now the dominant cost) toward ~10×; intra-dataset parallelism for the single largest dataset; partial FK indexes ([ord-schema#876](https://github.com/open-reaction-database/ord-schema/issues/876)) to cut the per-row index writes this loader now bottlenecks on.
4. **Temporarily larger boxes** during a rebuild — both the DB and the load host are 2 vCPU, so parallelism saturates fast; bump Aurora (e.g. `r6g.xlarge`) and use a bigger load VM, then scale back.
5. **`n_jobs > 1`** parallelizes across datasets (already supported) but not within the single dominant dataset, so it helps the tail, not the head.

For the current run: **let it finish** — it is ~88% through the worst pass, and killing it discards ~13h of uncommitted derive work for the big dataset.

## References

- [ord-schema#872](https://github.com/open-reaction-database/ord-schema/issues/872) — set-based compound SMILES derivation.
- [ord-schema#873](https://github.com/open-reaction-database/ord-schema/issues/873) — COPY-based bulk ingest.
- [ord-schema#864](https://github.com/open-reaction-database/ord-schema/pull/864) — batched derived passes (bounded the memory footprint; the pattern to extend to compounds).
- Prior entry: [`entries/2026-06-24-aurora-io-optimized-storage-mode.md`](2026-06-24-aurora-io-optimized-storage-mode.md) — its June I/O spike from "re-ingestion / optimization work" is this class of run.
- Prod account 482491871729, region us-east-1, cluster `cluster`, database `ord_20260629`.
