# Where the agent search cache can live

- **Date:** 2026-08-15
- **Author:** Steven Kearnes
- **Status:** final (pivot shipped in ord-schema#965; the cache is 381 MiB and belongs on S3)
- **Tags:** ord-schema, agents, duckdb, projection, parquet, aws, fargate, s3, caching, indexing

## Question

The agent executor materializes top-level projection columns as in-memory "narrow tables"
so repeated queries do not re-read Parquet. Held whole, the projection costs **18.46 GiB**
resident — `workups` 5.08, `inputs` 3.93, `outcomes` 3.04, and the rest. That number sets
the deployment: a Fargate task big enough to hold it, or slow queries.

So: is there anywhere other than the serving container to put that cache? RDS, ElastiCache,
a DuckDB-like managed service, Athena, S3 Tables — the question was asked as a survey of
places, and answered by discovering the premise was wrong.

## Summary

**The 18.46 GiB was never the information a predicate needs.** It is decoded *nesting*,
cached because the projection happens to be shaped that way. Pivot the repeated paths to
one row per element carrying only scalar leaves, and the same query surface is **2.68 GiB
resident, 381 MiB as Parquet**, and answers in **6–48 ms** where the nested form needs
1.3–3.4 s.

That is a 200× speedup and a 32× size reduction, with **identical answers** — the flat and
nested paths agree exactly on all four benchmark counts. The cache question dissolves:
381 MiB goes on S3, and DuckDB's external file cache holds it in whatever memory the
container has.

This is not a new shape. It is the **pivoted fact table** that
[the search-index entry](../2026-07-31-projection-search-index/README.md) measured and
[the EAV entry](../2026-07-31-eav-versus-projection/README.md) characterized as "an index over
specific paths, not a universal replacement." Both were right. What is new is that the
handful of specific paths a predicate can reach *is the whole query workload*, and that
pivoting them collapses the artifact far enough to change where it can be deployed.

Three claims did not survive their measurements, two of them mine:

1. **DuckDB's own storage cannot replace the narrow tables** — the corpus as a native
   DuckDB file is 5.41 GiB and answers the yield query in 3.35 s at a 2 GiB `memory_limit`
   and 3.28 s at 6 GiB. Insensitive to memory, and no better than Parquet.
2. **My explanation's prediction failed.** I argued the native file was slow because
   DuckDB caches compressed blocks rather than decoded vectors, and predicted flat Parquet
   would therefore show a memory-sensitivity curve. It shows none. The experiment could
   not have produced one — see finding 6.
3. **Directory sampling is invalid on this corpus.** One directory holds **88%** of it, so
   a four-directory subset drew 1,486 of 2,428,291 reactions and its extrapolation was
   noise. This also rules out per-directory sharding as a way to split the working set.

One cost finding reframes the survey that prompted the entry: **Fargate memory is among
the cheapest RAM in AWS.** Every managed cache considered costs more per gigabyte than the
container it would relieve.

## Method

Measured against the local projection artifacts (2,428,291 reactions, 2,016,224 distinct
structures, 53 file pairs across 48 directories, 1.53 GiB of source Parquet) on a 24 GiB
laptop, DuckDB 1.5.5, single process.

**Sizes here are binary** (1024³ for GiB, 1024² for MiB), unlike the decimal sizes in
[the EAV entry](../2026-07-31-eav-versus-projection/README.md). Resident size is measured with
`duckdb_memory()` filtered to `tag = 'IN_MEMORY_TABLE'`, taken as a delta across each
`CREATE TABLE` — not `duckdb_tables().estimated_size`, which reports a row count.

Scripts are in [`ASSETS.md`](ASSETS.md):

| script | what it measures |
| --- | --- |
| `probe_native.py` | the corpus as a native DuckDB file, at two memory limits |
| `probe_flat.py` | resident size of pivoted tables for four repeated paths |
| `probe_flat_query.py` | query latency against pivoted tables held in memory |
| `probe_flat_parquet.py` | the same queries read from Parquet, cold and warm, across memory limits |

Four queries carry the comparison. Three are the mixed benchmark's projection-only
clauses; the fourth is new and exists to test correctness rather than speed.

| query | why |
| --- | --- |
| `yield > 50%` | a predicate three repeated levels deep (`outcomes.products.measurements`) |
| `a white product` | two levels deep, a string equality |
| `above 350 K` | a scalar path with no quantifier at all |
| `desired product, yield > 50%` | **correlated**: the yield and `is_desired_product` must belong to the same outcome, which is where a flat index would over-return if element identity were lost |

## Findings

### 1. The nested cache is 12.05 GiB for three columns; pivoted, it is 2.68 GiB

One row per element, carrying that element's scalar leaves and its ordinal position:

| pivoted path | rows | resident | build |
| --- | --- | --- | --- |
| `outcomes.products.measurements` | 3,007,896 | 0.32 GiB | 785 s |
| `outcomes.products` | 2,673,037 | 0.23 GiB | 468 s |
| `inputs.components` | 11,950,037 | 1.35 GiB | 692 s |
| `workups` | 9,830,201 | 0.78 GiB | 3 s |
| **total** | **27.5M** | **2.68 GiB** | **~32 min** |

Against **12.05 GiB** for `outcomes` + `inputs` + `workups` held nested: a **4.5×**
reduction. The build is one-time and offline.

The 200,000-reaction row sample predicted 2.77 GiB against the full corpus's 2.68 GiB —
accurate to 3%, once sampled by row rather than by directory (finding 5).

### 2. Pivoted queries are 200× faster, with identical answers

Full corpus, best of three, tables held in memory:

| query | pivoted, in memory | nested native DuckDB | nested Parquet |
| --- | --- | --- | --- |
| `yield > 50%` | **0.016 s** | 3.35 s | ~4.8 s |
| `a white product` | **0.006 s** | 1.33 s | ~4.3 s |
| `above 350 K` | **0.001 s** | 0.03 s | 0.20 s |
| `desired product, yield > 50%` | **0.012 s** | — | — |

The counts are the load-bearing part. `yield > 50%` returns **729,520** reactions and
`a white product` returns **139,095** — matching the nested path exactly. The correlated
query returns **23,608**, a sane subset of the 729,520 reactions carrying a >50% yield, so
carrying `outcome_index` and `product_index` on the pivoted row preserves element binding.
This is the same requirement
[the structure-search entry](../2026-08-08-structure-search-without-the-orm/README.md) found
mandatory, where reaction-granularity intersection over-returned by 94%.

### 3. As Parquet the whole artifact is 381 MiB, and reads at 20–48 ms

Written sorted on the predicate columns with ZSTD:

| table | Parquet |
| --- | --- |
| `reaction` | 282.5 MiB |
| `measurement` | 47.0 MiB |
| `product` | 51.2 MiB |
| **total** | **381 MiB** |

Reading straight from Parquet costs 0.020–0.048 s against 0.006–0.016 s in memory — about
3× slower and irrelevant in absolute terms. Counts match for a third time.

Note the distribution: **282.5 MiB of the 381 MiB is `reaction`**, nearly all of it
`notes.procedure_details` free text. The predicate-answering core — `measurement` plus
`product` — is **98 MiB**. Free text is a text-search concern and can be a separate
artifact, so the hot set is smaller still.

### 4. DuckDB's native storage does not cache what nested data costs

The corpus written as a DuckDB database file is **5.41 GiB**, and answers:

| query | `memory_limit=2GB` | `memory_limit=6GB` |
| --- | --- | --- |
| `yield > 50%` | 3.35 s | 3.28 s |
| `a white product` | 1.33 s | 1.34 s |
| `above 350 K` | 0.03 s | 0.03 s |

No better than Parquet, and — the decisive part — **6 GiB exceeds the whole 5.41 GiB
file**, so the entire database fit in the buffer pool and it was still slow. That rules out
IO and leaves decode: DuckDB's buffer pool caches compressed storage blocks, and
reconstructing `LIST(STRUCT(...))` into vectors happens on every scan regardless. The
narrow tables earn their complexity by paying that reconstruction once, which is also why
their in-memory form is 18.46 GiB against 5.41 GiB on disk.

Corroborating evidence from the pivot builds: the `reaction` table, pulling
`conditions.temperature.setpoint_kelvin` out of a deep struct across 2,428,291 rows, built
in **2 seconds**. Scalar struct-field pruning was never the problem. Every expensive build
in these probes is a *repeated* level being unnested.

### 5. The corpus is 88% one directory, so directory sampling and directory sharding both fail

`projections/11` is 1,383 MiB of 1,570 MiB. A subset probe over four other directories drew
**1,486 reactions** and reported 2.1 MiB for 2,062 rows — roughly 1,067 bytes per row for
nine narrow columns, which is DuckDB's block granularity rather than data. Extrapolating it
×1634 produced a plausible-looking 9.62 GiB that was pure noise; the correct figure is
2.68 GiB.

Two consequences. Sample by row, not by file or directory. And **per-directory sharding
cannot split this working set** across tasks — one shard would carry nearly all of it.

### 6. My memory-sensitivity prediction failed, and the test could not have confirmed it

Having explained finding 4 as "the cache holds compressed blocks, not decoded vectors," I
predicted flat Parquet would behave oppositely: cold ≫ warm, and warm improving with
`memory_limit`. Measured at 1, 4, and 8 GiB, cold equals warm and all three limits are
indistinguishable.

The experiment was incapable of showing otherwise, for two reasons. The Parquet had just
been written, so every "cold" read hit the OS page cache — cold only with respect to
DuckDB's cache, never with respect to storage. And at 381 MiB the dataset fits entirely
inside the smallest limit tested, so no eviction pressure existed for a curve to appear in.

The finding-4 conclusion stands regardless, on the 6 GiB-exceeds-5.41 GiB evidence above,
which needs no curve. But the mechanism claim itself remains unverified, and a real cold
read from S3 is still owed.

### 7. Fargate memory is among the cheapest RAM in AWS

Approximate us-east-1 on-demand, for roughly 30 GiB. **Verify before relying on these** —
they move.

| where | config | ~$/hr | ~$/mo |
| --- | --- | --- | --- |
| Fargate ARM64 | 4 vCPU / 30 GiB | 0.24 | 172 |
| Fargate x86 | 4 vCPU / 30 GiB | 0.30 | 215 |
| EC2 `r7g.xlarge` | 4 vCPU / 32 GiB | 0.21 | 155 |
| ElastiCache `cache.r7g.xlarge` | 26 GiB | 0.33 | 240 |
| RDS `db.r6g.xlarge` | 4 vCPU / 32 GiB | ~0.45 | ~330 |

Every managed cache costs more per gigabyte than the container it would relieve, and adds a
network hop. The reason to move a cache off the serving task is therefore never price per
gigabyte — it is sharing across tasks, surviving restarts, or exceeding Fargate's 120 GiB
ceiling. Worth naming which one is being bought before paying for it.

At the pivoted size the comparison is moot: a 2 vCPU / 8 GiB task holds the flat index and
the RDKit library together.

### 8. The candidates, after the pivot

- **S3 + DuckDB** — the recommendation. 381 MiB of sorted Parquet, read with
  `enable_external_file_cache` (on by default in 1.5.5) and `parquet_metadata_cache`
  (off by default; turn it on). Container memory becomes an automatic LRU over column
  chunks, sized by `memory_limit` alone.
- **RDS / Aurora** — works, and uniquely retires the RDKit floor via the cartridge and its
  GiST index. Costs a second compiler emitting joins over normalized tables. The only
  option that addresses finding 9.
- **ElastiCache** — cannot hold decoded rows usefully; would hold posting lists, which
  means writing an execution layer. Unnecessary at 381 MiB.
- **MotherDuck / ClickHouse Cloud** — genuinely viable for a small flat database, and now
  unnecessary for the same reason.
- **Athena** — the wrong reader, and not a cache at all: S3 would be the cache, Athena one
  way to read it. It carries a query-planning floor, an account concurrency quota, and an
  ID-handoff problem, since the RDKit half produces a structure-ID set that must meet the
  projection half — a local semi-join in process, but a 262,144-byte query-text limit or an
  S3 round trip through Athena. Its value proposition is "you don't need a machine," and
  finding 9 says we need one anyway. Athena *is* the right tool for **building** the
  pivoted artifact.
- **S3 Tables / Iceberg** — not the win. Iceberg earns its keep on mutation; these
  artifacts are immutable and versioned, and [`artifacts.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/artifacts.py)
  already stamps them. It adds catalog and manifest round trips to the cold path, which is
  where this design is weakest, and DuckDB's support is read-only and in preview from
  nightly builds. Plain Parquet on plain S3 is readable by Athena and DuckDB both; a table
  format is not needed for read sharing. Revisit on incremental updates, ~100× growth, or a
  second concurrent writer.

### 9. The chemistry is the only thing that still needs memory

The pivot moves the projection cache to S3. It does nothing to the resident floor, which is
the RDKit `SubstructLibrary` (~1.5 GiB) plus the occurrence index (14.1M rows, ~130 MiB).
Substructure screening and verification are RDKit in-process, and
[the structure-search entry](../2026-08-08-structure-search-without-the-orm/README.md) established
that verification is irreducible. Postgres with the RDKit cartridge is the only option on
this list that retires it.

## Conclusions / next steps

The survey question — *where else can the cache live?* — had an answer nobody was looking
for: **make it small enough that the question stops mattering.** 18.46 GiB of decoded
nesting became 381 MiB of Parquet by storing what a predicate reads instead of what the
schema nests.

This closes, for the executor's purposes, the open question
[the search-index entry](../2026-07-31-projection-search-index/README.md) left: a pivoted fact table
does not replace the projection, but it *does* replace the projection **as a query cache**,
which is a smaller claim and a fully measured one.

### What was built

The pivot shipped as `ord_schema.search.pivot` in
[ord-schema#965](https://github.com/open-reaction-database/ord-schema/pull/965); the
design and the implementation plan are kept beside this entry as
[the design](pivoted-element-index-design.md)
and [the plan](pivoted-element-index-plan.md).
Three things it settled that this entry left open, and one it did not:

**Quantifier semantics agree, and correlation needs the whole ordinal prefix.** Over the
whole corpus, `exists`, `not exists`, `forall`, and a body whose leaf is NULL all return
identical reaction-ID sets on both routes. The correlation is the part that had to be
built rather than checked: "a desired product with a yield above 50%" answers 22,666
reactions on `(reaction_id, outcome_index, product_index)` and **23,608** on anything
less — 942 wrong. Since ORD is effectively single-outcome, dropping the *outcome*
ordinal changes nothing at all, so only a corpus stating both products in one outcome
exposes the product-level error.

**Answered end to end, warm, against the same queries over the elements:**

| query | pivot | elements |
| --- | --- | --- |
| a white product | 0.050s | 0.936s |
| yield > 50% | 0.086s | 2.758s |
| every product is desired | 0.070s | 2.055s |
| **not** a yield above 50% | 0.098s | 3.480s |
| a solvent input | 0.178s | 4.229s |

**Building one is far more expensive than the column it competes with.** The question
this entry left unmeasured now has an answer, and it is lopsided: a pivot over
`outcomes.products` is **0.45 GiB built in 461 s**, where materializing the whole nested
`outcomes` column is **3.23 GiB in 4.1 s**. Seven times smaller to hold, and a hundred
times slower to build. That is the case for artifacts stated in numbers: the size win is
real and the build belongs offline, which is what `scripts/derive_pivots.py` and
`Corpus(pivots_dir=...)` are for.

**Pruning only the repeated fields is too coarse.** A `workups` element carries a whole
`ReactionInput` besides, so its pivot is **4.4 GiB** against the nested column's 5.08 —
a 13% reduction, where five hand-picked leaves gave 0.78 GiB. It exceeds the 4 GiB
default budget, is refused, and the projection answers. Pruning to referenced subtrees
is the fix and is not built.

### Still open

1. **Measure a genuinely cold read from real S3**, which finding 6 could not produce.
2. **Reassess the narrow-table subsystem.** If DuckDB's external file cache over flat
   Parquet performs as findings 2 and 3 suggest, the budget, LRU, eviction, and refusal
   machinery in [ord-schema#964](https://github.com/open-reaction-database/ord-schema/pull/964)
   is replaced by `memory_limit`, at column-chunk granularity rather than whole
   top-level columns. It rests on the unmeasured S3 step above, and #964 is correct on
   its own terms.
3. **Derive a serialized `SubstructLibrary`** as an artifact too, so the ~1.5 GiB that
   pins a resident process is loaded rather than built.

## References

- Prior entries: [projection search index](../2026-07-31-projection-search-index/README.md),
  [EAV versus projection](../2026-07-31-eav-versus-projection/README.md),
  [structure search without the ORM](../2026-08-08-structure-search-without-the-orm/README.md),
  [agent access: sidecars or ORM](../2026-07-30-agent-access-sidecars-or-orm/README.md),
  [query IR versus generated SQL](../2026-08-07-query-ir-versus-generated-sql/README.md)
- [ord-schema#962](https://github.com/open-reaction-database/ord-schema/pull/962) — the
  occurrence index, spent one quantifier at a time
- [ord-schema#964](https://github.com/open-reaction-database/ord-schema/pull/964) — the
  narrow-table memory budget
- Scripts: [`ASSETS.md`](ASSETS.md)
- [Streamlining access to tabular datasets stored in Amazon S3 Tables with DuckDB](https://aws.amazon.com/blogs/storage/streamlining-access-to-tabular-datasets-stored-in-amazon-s3-tables-with-duckdb/)
  — AWS Storage Blog, the S3 Tables walkthrough assessed in finding 8
