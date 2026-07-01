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

## Conclusions / next steps

The ORM is the right tool for serving/reading; it is the wrong tool for bulk loading. Plan, highest-leverage first:

1. **Set-based compound-SMILES derive** ([ord-schema#872](https://github.com/open-reaction-database/ord-schema/issues/872)) — pull SMILES from `ord.compound_identifier` in one SQL pass, RDKit-fallback only for compounds without a SMILES identifier. Smaller, lower-risk; do first.
2. **`COPY`-based ingest** ([ord-schema#873](https://github.com/open-reaction-database/ord-schema/issues/873)) — flatten each proto to per-table tuples and stream via psycopg `COPY`, bypassing the ORM unit of work; parallelize proto→tuple across cores. **Prototype-gated:** build a loader for one dataset against a scratch DB and benchmark real rxn/s vs. the ORM path before committing to a PR.
3. **Temporarily larger boxes** during a rebuild — both the DB and the load host are 2 vCPU, so parallelism saturates fast; bump Aurora (e.g. `r6g.xlarge`) and use a bigger load VM, then scale back.
4. **`n_jobs > 1`** parallelizes across datasets (already supported) but not within the single dominant dataset, so it helps the tail, not the head.

For the current run: **let it finish** — it is ~88% through the worst pass, and killing it discards ~13h of uncommitted derive work for the big dataset.

## References

- [ord-schema#872](https://github.com/open-reaction-database/ord-schema/issues/872) — set-based compound SMILES derivation.
- [ord-schema#873](https://github.com/open-reaction-database/ord-schema/issues/873) — COPY-based bulk ingest.
- [ord-schema#864](https://github.com/open-reaction-database/ord-schema/pull/864) — batched derived passes (bounded the memory footprint; the pattern to extend to compounds).
- Prior entry: [`entries/2026-06-24-aurora-io-optimized-storage-mode.md`](2026-06-24-aurora-io-optimized-storage-mode.md) — its June I/O spike from "re-ingestion / optimization work" is this class of run.
- Prod account 482491871729, region us-east-1, cluster `cluster`, database `ord_20260629`.
