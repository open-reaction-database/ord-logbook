# Full-ORD end-to-end run on the sharded pipeline: ingest/SMILES/RDKit land fast, classification hits a CPU wall

- **Date:** 2026-07-02
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** aws, aurora, cost, ingest, derived, rdkit, classification, gpu, benchmark

## Question

With the intra-dataset sharding now merged across every derived pass (ord-schema #883 SMILES, #887 RDKit, #888 classification), do a clean end-to-end run of the **entire** ORD into a fresh database — ingest, SMILES, RDKit, **and** reaction classification — on the current code. Track per-stage timings and produce a cost estimate.

## Summary

- **Ingest + SMILES + RDKit complete the full ORD (2,428,291 reactions across 53 datasets) in ~70 min of pipeline wall-clock** on the scaled writer: ingest **17m25s**, full SMILES derivation **~10.7 min**, RDKit **41m38s**. All stages ran clean (`rc=0`) with healthy memory.
- **Reaction classification is not viable on this CPU VM — it is a multi-day job.** Rxn-INSIGHT/rxnmapper is a BERT transformer; the dev VM (`c8i.4xlarge`) has **no GPU**, so inference runs on CPU. Committed throughput was **~0.7 reactions/s** (1,390 rows in ~33 min), which extrapolates to **~40 days** for 2.4M reactions — clearly the wrong order of magnitude. Classification was aborted and **deferred to a separate GPU job**.
- **The scaled writer is the right resource for ingest/SMILES/RDKit, but the wrong one for classification.** RDKit is writer-bound (the cartridge does mol-parsing + GiST structure indexing on the writer; the 16-vCPU client sat at load ~0). Classification is the opposite — client-CPU-bound with light writes — so keeping the scaled writer up during it wastes the premium.
- **Cost of the whole session ≈ $4.4 incremental** (VM `c8i.4xlarge` $1.94 + writer-scale premium ~$2.5, plus modest Standard-storage I/O). About **$1.9 of that was avoidable rework** (a stale VM checkout forced a re-ingest, and the classification attempt burned scaled-writer time). A clean run — current VM, classification deferred up front — would be **~$2.5**.
- **Operational lesson: pull the VM checkout before benchmarking.** The VM was parked at `50c27e0` (pre-sharding); its derived stage silently ran the *old* unsharded path (per-dataset classification, load spiked to ~105 on 16 cores) before I caught the mismatch and updated to `cb244e3`.

## Method

- **Code:** ord-schema `cb244e3` (tip of `main`; includes #883/#887/#888). The VM started at `50c27e0` and was fast-forwarded mid-run — see the rework note below.
- **Database:** a fresh `ord_20260702` on the shared Aurora PostgreSQL cluster (`cluster`, engine 16.11, **Standard** storage), created and schema-prepared (`prepare_database`, 99 partial FK indexes) before ingest.
- **Infra:** dev VM `i-080fa23d58cf7e813` = `c8i.4xlarge` (16 vCPU / 32 GB, no GPU); Aurora writer `cluster-instance-0` scaled `db.t4g.large → db.r7g.2xlarge` for the run and restored afterward.
- **Commands** (`ord_schema.orm.scripts.add_datasets`, `--n_jobs 16`, password sourced from Secrets Manager into the environment):
  - Ingest: `--stages ingest`
  - Derived + classification: `--stages derived --classify_reactions` (classification pool defaults to `min(n_jobs, 4)` = 4 model-loading workers)
  - After aborting classification: `--stages derived` (no `--classify_reactions`) to finish SMILES + RDKit. The SMILES pass is idempotent (`NOT EXISTS` skip), so it completed the last 0.4% and moved to RDKit without redoing work.
- **Orchestration/monitoring** ran from a laptop driving the VM over SSM (scripts in the session scratchpad: `prepare_e2e.sh`, `launch_ingest_e2e.sh`, `launch_derived_e2e.sh`, `poll_until.sh`, `classify_rate.sh`, `rdkit_progress.sh`, `cleanup_e2e.sh`). The actual jobs ran in `tmux` on the VM. Progress was tracked both from tqdm logs and directly from DB row counts (the shard-level tqdm bar is misleading — it only ticks when a whole shard commits, and the big datasets have huge shards).

## Findings

### Stage timings

| Stage | Wall-clock | Result |
| --- | --- | --- |
| Ingest (COPY, row-group sharded, `n_jobs=16`) | **1,045 s (17m25s)** | 2,428,291 reactions; ~2,324 rxn/s |
| SMILES derivation (sharded, 93 shards) | **~10.7 min** | 2,418,635 reaction SMILES (99.6%) |
| Reaction classification (CPU) | aborted after ~33 min | 1,390 rows (~0.7 rxn/s) → **multi-day**, deferred |
| RDKit cartridge (sharded by SMILES hash) | **41m38s** | 1,432,316 mols; 1,653,622 reactions |

Ingest was run twice (once on the stale `50c27e0`, once on `cb244e3`) and clocked **1,041 s** then **1,045 s** — the ingest path is unchanged across those commits, confirming stability. End-to-end pipeline work excluding classification ≈ **70 min**.

### Final row counts (`ord_20260702`)

| Table | Rows |
| --- | --- |
| `ord.dataset` / `public.datasets` (finalized) | 53 / 53 |
| `ord.reaction` = `public.reactions` | 2,428,291 |
| `ord.compound` | 17,043,157 |
| `derived.reaction_smiles` | 2,418,635 |
| `derived.compound_smiles` | 11,544,019 |
| `derived.product_compound_smiles` | 2,605,008 |
| `rdkit.mols` / `rdkit.reactions` | 1,432,316 / 1,653,622 |
| `derived.reaction_classes` | 1,390 (partial, from the aborted classify pass) |

### Classification is CPU-bound and needs a GPU

The classify pass loads a Rxn-INSIGHT/rxnmapper model per worker (pool capped at 4 to bound memory) and runs transformer atom-mapping per reaction. On CPU this is single-digit reactions/s/worker at best. Direct measurement: `derived.reaction_classes` grew to **1,390 rows and then held flat for 6+ minutes** while four workers each ground on a large shard (shards commit only on completion). The tqdm shard bar froze at 4/93 for ~30 min. Benign `Token indices sequence length is longer than the specified maximum (547 > 512)` warnings confirm the tokenizer path is active — the model is simply slow on CPU. Memory was never the constraint (4 models, ~29.5 GB free throughout); **compute is**.

At ~0.7 committed rxn/s aggregate, 2.4M reactions is ~40 days. Even a generous 10 rxn/s CPU estimate is ~3 days. A GPU (rxnmapper is exactly the workload GPUs exist for) should bring this to **hours**.

### RDKit is writer-bound and slows as the index grows

RDKit ran with the 16-vCPU client at **load ~0** — all work is on the writer (mol parsing + GiST structure index). Insert rate started ~2,700 mols/s and decayed to ~450 mols/s as the cartridge index grew; per-shard time on the largest dataset climbed from a few seconds to ~200 s. Lock waits appeared briefly at cartridge/index warmup (8 of 16 workers) then cleared to 0 — the SMILES-hash sharding keeps the concurrent inserts on disjoint keys as designed. This is the writer-bound long pole, and the scaled `r7g.2xlarge` is what makes it tolerable.

### Sharding and memory-bounding behaved

On the current code the SMILES pass fanned one large dataset across parallel shards (93 shard work-items over 53 datasets) with load a sane 6–8; the classify pool held to 4 models with flat memory. Contrast the stale `50c27e0` path, whose unsharded per-dataset classification spiked load to ~105 on 16 cores — the motivation for #888 in one screenshot.

### Cost

Standard on-demand list prices (us-east-1): VM `c8i.4xlarge` $0.74968/hr; Aurora `db.r7g.2xlarge` $1.106/hr; baseline `db.t4g.large` $0.146/hr.

| Line item | Duration | Cost |
| --- | --- | --- |
| VM `c8i.4xlarge` | 2.58 hr | $1.94 |
| Writer scaled `r7g.2xlarge` (gross) | ~2.6 hr | ~$2.9 |
| Writer **premium** over baseline `t4g.large` | ~2.6 hr | **~$2.5** |
| **Incremental run cost (VM + writer premium)** | | **~$4.4** |
| — of which non-productive (stale re-ingest + aborted classify) | ~1.1 hr | ~$1.9 |

Aurora I/O is billed separately under Standard storage and is not precisely metered here (CloudWatch volume-I/O returned implausible values over the window); the bulk load of ~20M rows plus indexes adds a smaller I/O line on top. This is the recurring argument for IO-Optimized during bulk loads (see [2026-06-24](../2026-06-24-aurora-io-optimized-storage-mode/README.md)).

## Conclusions / next steps

- **Run classification as a separate GPU job.** Provision a GPU instance (e.g. `g5.xlarge`/`g6.xlarge`), install the `reaction-class` extra, and classify against the already-populated `ord_20260702`. `classify_dataset`/`update_reaction_classes` are classify-only (they do not re-derive SMILES), and the pass is sharded, so it parallelizes cleanly. Expect hours, not days. Track this as an ord-schema issue.
- **Keep classification off the scaled-writer critical path.** It is client-compute-bound with light writes, so it should run against the baseline `t4g.large` writer — scaling up buys nothing for it. Ingest/SMILES/RDKit are what justify the temporary scale-up.
- **`git pull` the VM before any benchmark.** A stale checkout silently ran the old code path and cost ~$1.9 in rework here. Worth a one-line guard in the run scripts.
- **The write-bound stages are in good shape.** Full-ORD ingest + SMILES + RDKit in ~70 min on a temporarily-scaled writer is a solid baseline; the remaining lever is the writer itself (auto-scaling per [2026-07-01](../2026-07-01-aurora-cluster-topology/README.md)).

## References

- ord-schema PRs: [#877](https://github.com/open-reaction-database/ord-schema/pull/877) (COPY ingest), [#879](https://github.com/open-reaction-database/ord-schema/pull/879) (row-group sharding), [#883](https://github.com/open-reaction-database/ord-schema/pull/883) (SMILES sharding), [#887](https://github.com/open-reaction-database/ord-schema/pull/887) (RDKit sharding), [#888](https://github.com/open-reaction-database/ord-schema/pull/888) (classification sharding). Run code at `cb244e3`.
- Prior entries: [2026-07-01 Aurora cluster topology](../2026-07-01-aurora-cluster-topology/README.md), [2026-06-24 Aurora IO-Optimized storage mode](../2026-06-24-aurora-io-optimized-storage-mode/README.md).
