# Where the agent search cache can live

- **Date:** 2026-08-15
- **Author:** Steven Kearnes
- **Status:** final (pivot shipped in ord-schema#965, footer cache in ord-schema#968; the four hot levels are 514 MB of Parquet and belong on S3)
- **Tags:** ord-schema, agents, duckdb, projection, parquet, aws, fargate, s3, caching, indexing
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

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
the artifact goes on S3, and the container holds parsed Parquet footers rather than
decoded columns.

Two things in that paragraph were sharpened by what shipped, and both are worth reading
before the figures above are quoted. The pivot that shipped holds every non-repeated leaf
rather than the handful a benchmark touched, which is what makes a query the pivot cannot
answer decline structurally — and costs 3.4× the size measured here (finding 12). And it
is *not* DuckDB's external file cache that makes this work: that one is worth nothing at
all, and `parquet_metadata_cache` is worth 17× (finding 10).

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

Scripts are in [`assets/`](assets/):

| script | what it measures |
| --- | --- |
| `probe_native.py` | the corpus as a native DuckDB file, at two memory limits |
| `probe_flat.py` | resident size of pivoted tables for four repeated paths |
| `probe_flat_query.py` | query latency against pivoted tables held in memory |
| `probe_flat_parquet.py` | the same queries read from Parquet, cold and warm, across memory limits |
| `probe_cache.py` | four cache configurations over the projections, raw DuckDB |
| `probe_footer.py` | the same question through a real `Corpus`, with and without materialization |
| `probe_struct_pushdown.py` | whether a scan pays for struct fields it does not name |
| `probe_width.py` | where the bytes sit inside each level, read from the footers |
| `probe_element.py` | what each field of a pivot’s element costs in memory |
| `derive_probe_pivots.py` | derives the pivot artifacts the route benchmark reads |
| `bench_artifacts.py` | pivots as artifacts, against in memory, against the elements |
| `probe_subsume.py` | structure queries on the index, the pivots, and the elements |
| `probe_floor.py` | process residency of each startup step, at three DuckDB limits |
| `probe_index_limit.py` | where the index build's memory floor sits, and what it spills |
| `probe_index_shape.py` | whether building the index path by path lowers that floor |
| `probe_index_chunked.py` | the same build one projection file at a time |
| `probe_index_default.py` | both build shapes where nothing is constrained |

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
carrying the ordinals on the pivoted row preserves element binding.

That 23,608 is wrong, and being sane is how it passed. The probe's `product` table was
built without `WITH ORDINALITY`, so the correlation ran on `(reaction_id, outcome_index)`
and answered for a *different product* of the same outcome. The right answer is
**22,666**; see "What was built" below. The requirement stands and the number does not.

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
  chunks, sized by `memory_limit` alone. Finding 10 measures both settings: only the
  second one does anything, and it does a great deal.
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
  artifacts are immutable and versioned, and [`artifacts/base.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/artifacts/base.py)
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

**The index figure here is wrong, and the heading with it.** Measured directly rather
than carried forward, the occurrence index is **18,847,978 rows and 1.19 GiB**, built in
58 s — nine times the 130 MiB stated above, which had been repeated into
[the design note](assets/pivoted-element-index-design.md) and the ord-schema README
before anyone put a number on it. A row is three strings and an integer, and finding 13
is why that is expensive: an in-memory string is not a Parquet one.

So the floor is the library at ~1.5 GiB *and* the index at 1.19 GiB, and the index is not
chemistry — it is reaction lookup. Call the resident floor 4 GB rather than 3. The
irreducible-verification claim stands; "the chemistry is the only thing" does not.

### 10. What a projection query costs is footer parsing, not reading

Finding 8 named two DuckDB settings and recommended both. Measured over the full corpus,
one of them does nothing at all:

| configuration | temperature filter | stirring group-by | held |
| --- | --- | --- | --- |
| neither cache | 0.880 s | 0.879 s | — |
| external file cache | 0.841 s | 0.839 s | 0.19 GB of file bytes |
| file **and** metadata cache | 0.050 s | 0.049 s | + 0.20 GB of parsed footers |
| materialized column | 0.003 s | 0.003 s | 1.28 GB table |

The external file cache holds file *bytes*; nothing here was ever IO-bound, so holding
them changes a query by less than 5%. What costs the time is *parsing* — a 442-leaf
schema over 53 files, with statistics per row group, decoded again on every scan
however few leaves the query then reads. `parquet_metadata_cache` holds the parsed
result and removes it.

Through a real `Corpus`, warm, with identical row counts on every route:

| query | footers reparsed | footers held | held as a column set |
| --- | --- | --- | --- |
| temperature filter | 0.759 s | 0.096 s | 0.032 s |
| group-by on stirring type | 0.728 s | 0.055 s | 0.003 s |
| temperature and city | 0.712 s | 0.029 s | 0.002 s |
| substring of a safety note | 0.713 s | 0.026 s | 0.001 s |

The parsed footers cost ~200 MB across the whole corpus and are bounded by the *files*
rather than by what is asked of them, which is what makes them worth spending
unconditionally where a column set costs gigabytes apiece. Shipped in
[ord-schema#968](https://github.com/open-reaction-database/ord-schema/pull/968), which
also covers the invalidation this now leans on: a file rewritten under an open corpus is
re-read, including a rewrite inside the same second.

DuckDB's file cache is bounded by `memory_limit` and fills what it is given — 752 MB at a
1 GiB limit, 2.66 GB at 3 GiB — and is evicted under pressure. The parsed footers do not
shrink that way, so on a small limit they are a fifth of it.

### 11. A query does not pay for the struct fields it does not name

A pivot's `element` is one struct column holding every field the level's element carries,
so a wide level makes a wide struct. Whether that costs a *query* anything decides
whether pruning the element further is worth doing. Over 3,000,000 rows, a four-field
struct, 193 MiB of zstd Parquet:

| the query touches | time |
| --- | --- |
| the narrow field only | 0.003 s |
| one wide field | 0.016 s |
| three wide fields | 0.052 s |
| the whole struct | 0.057 s |

Parquet stores a struct's fields as separate columns and DuckDB reads only the ones
named. A wide pivot artifact therefore costs disk, and nothing else.

### 12. Generality cost 3.4×, and the width is not prunable

The 2.68 GiB in finding 1 is not what shipped. That probe held a **hand-picked handful of
scalar leaves** per level — five columns for `workups`, four for `outcomes.products` —
chosen because the benchmark happened to touch them. The shipped pivot holds *every*
non-repeated leaf, which is what lets a body reaching a dropped field fail to resolve and
decline to the projection, rather than a second list of covered paths that someone has to
keep honest. Forty leaves for `workups` rather than five, and 4.40 GiB rather than 0.78.

Across the four levels that matter: **9.21 GiB against 2.68 GiB**, for a query surface
that answers any predicate the level supports instead of the ones a benchmark used.

So: can the difference be pruned back? Uncompressed Parquet bytes below each level, split
into what the pivot keeps and what pruning the repeated fields already dropped:

| level | kept | already pruned | the biggest kept field |
| --- | --- | --- | --- |
| `workups` | 0.373 GiB | 0.536 GiB | `details` 62.6% |
| `inputs.components` | 0.235 GiB | 0.240 GiB | `smiles` 49.6% |
| `outcomes.products` | 0.118 GiB | 0.310 GiB | `smiles` 85.1% |
| `outcomes.products.measurements` | 0.108 GiB | 0.067 GiB | `authentic_standard` 29.9% |

Nothing on that right-hand column is prunable without losing questions people ask.
`workups.details` is the free text a `contains` predicate reads; `smiles` is the path a
structure predicate is written against; `authentic_standard` is a compound a query
reaches through. The weight is in the fields that earn their place.

### 13. Parquet charges for data; DuckDB charges for shape

The disk figures above do not explain the memory ones. A pruned `workups` element is
0.373 GiB of uncompressed Parquet and 4.18 GiB once the pivot is built. Measured field by
field, across four pivots built one per process:

| level | rows | leaves | held | per row |
| --- | --- | --- | --- | --- |
| `workups` | 9,830,201 | 40 | 4.18 GiB | 457 B |
| `inputs.components` | 11,950,037 | 18 | 2.64 GiB | 237 B |
| `outcomes.products.measurements` | 3,007,896 | 48 | 1.34 GiB | 477 B |
| `outcomes.products` | 2,673,037 | 7 | 0.39 GiB | 158 B |

The tell is in two neighboring fields of a workup:

| field | uncompressed Parquet | held in memory |
| --- | --- | --- |
| `duration_seconds` | 0.005 GiB | 0.099 GiB |
| `duration_precision_seconds` | 0.002 GiB | 0.099 GiB |

They are the same type and one of them is almost never populated. Parquet's
run-length-encoded definition levels make an all-NULL column nearly free; DuckDB's
in-memory column is a full-width vector plus a validity mask whether or not anything is
in it. `outcomes.products.measurements` has the same pair in
`wavelength_nanometers` and `wavelength_precision_nanometers`, both 0.030 GiB. The single
largest field of any of these is `inputs.components.amount` at 1.064 GiB: nine mostly-NULL
doubles per row, one for each way a quantity can be stated.

So the in-memory cost tracks **leaf count**, not data. That is why the width matters when a
pivot is held and stops mattering when it is a file — and it is why the prune that would
actually pay is dropping empty leaves, which is a prune on the *data* rather than the
schema, and would give two shards of one corpus different schemas.

A fixed cost worth naming: `reaction_id` plus the ordinals is 0.453 GiB for `workups` and
0.623 GiB for `inputs.components`, 11% and 24% of those pivots. Held as Parquet the
`reaction_id` string compresses; held in memory it does not.

### 14. As artifacts the pivots are 514 MB, and answer as fast as held ones

The four levels derived to Parquet with `scripts/derive_pivots.py`, one file per
projection:

| level | held | as an artifact |
| --- | --- | --- |
| `workups` | 4.18 GiB | 149 MB |
| `inputs.components` | 2.64 GiB | 224 MB |
| `outcomes.products` | 0.39 GiB | 104 MB |
| `outcomes.products.measurements` | 1.34 GiB | 37 MB |
| **total** | **9.21 GiB** | **514 MB** |

The ratios invert between levels exactly as finding 13 predicts. `workups` is 28× smaller
as a file — 40 leaves, most NULL in most rows. `outcomes.products` is only 4× smaller: 7
leaves dominated by `smiles`, high-entropy text neither representation compresses away.

Then the same query set on all three routes, warm, through a real `Corpus`:

| query | artifacts | in memory | elements |
| --- | --- | --- | --- |
| a white product | 0.061 s | 0.054 s | 0.737 s |
| `yield > 50%` | 0.099 s | 0.085 s | 2.384 s |
| every product is desired | 0.076 s | 0.070 s | 1.781 s |
| **not** a yield above 50% | 0.114 s | 0.093 s | 3.113 s |
| an extraction workup | 0.114 s | 0.103 s | 2.341 s |
| "reflux" in a workup | 0.147 s | 0.105 s | 2.239 s |
| a solvent input | 0.176 s | 0.155 s | 1.794 s |
| above 350 K | 0.033 s | 0.033 s | 0.032 s |

Identical row counts on all three. `above 350 K` is the control — a scalar path with no
quantifier, where no pivot is involved and nothing moves.

**A pivot read from Parquet is within tens of milliseconds of the same pivot held in
memory**, and 6–27× faster than the elements. Publishing all four as views took **0.9
seconds and no memory**, against **32 minutes and 9.21 GiB** to build them in process.

The three routes held, at the end of the run:

| route | in-memory tables | parsed footers | DuckDB file cache |
| --- | --- | --- | --- |
| artifacts | 1.91 GB | 0.21 GB | 1.37 GB |
| in memory | 11.13 GB | 0.20 GB | 6.76 GB |
| elements | 1.78 GB | 0.20 GB | 4.57 GB |

The artifact route's 1.91 GB is column sets the queries materialized, not pivots — the
pivots are files. Adding 212 pivot artifacts to the corpus moved the parsed footers by
10 MB.

So the answer to a wide level is not a narrower pivot. It is a pivot that is a file.

### 15. The occurrence index survives, on latency rather than on memory

The index was kept because it is 130 MB where the pivots that would replace it were
gigabytes held. Finding 14 removes that argument entirely, so the question was reopened
and measured properly — and the premise turned out to be wrong twice over, since the
index is 1.19 GiB rather than 130 MB (finding 9). Memory was never the axis that
separated them, and on the axis it was argued on they are within 30% of each other.

The pivot route answers a structure predicate **correctly**. A structure predicate
compiles to a bit test on `element.structure_id` plus the row's `structure_offset`, and
inside a pivot's semi-join that offset is unqualified and binds to the correlated
reaction — which sits in exactly one projection file, so it is already the right offset.
No plumbing was needed to find this out; it works today.

| query | index | pivots | elements | rows |
| --- | --- | --- | --- | --- |
| pyridine anywhere | 0.070 s | 0.958 s | 2.376 s | 660,352 |
| pyridine as the solvent | 0.015 s | 0.597 s | 1.589 s | 25,805 |
| pyridine solvent, above 350 K | 0.021 s | 0.476 s | 1.022 s | 2,143 |
| a pyridine product | 0.165 s | 0.273 s | 3.427 s | 551,210 |

Identical row counts on all three routes. And the index is **4–40× faster than the
pivots**, so subsuming it would be a large regression on exactly the queries the whole
system exists to answer.

The reason is shape. The index is one narrow in-memory table — reaction ID, path,
corpus-wide structure ID, `reaction_role` — with nothing else on the row. The pivot is a
file holding every leaf of the element, and answering a structure predicate from it means
decoding two of them for 11.95M rows and testing each against a 2 MB bitstring. Being
free to hold is not the same as being cheap to read.

So: **keep the index.** That is the same conclusion reached before finding 14, for a
reason that is not the one given at the time. The memory argument was never the load-
bearing one, and had the pivots been artifacts from the start it would have pointed the
wrong way.

### 16. The index cannot be built in a small container, and says so late

Findings 9 and 15 measure what the index costs to *hold*. What it costs to *build* is a
separate number and a larger one, and it decides whether a container can run substructure
search at all.

Process resident size, building each part in the order a first substructure query would,
with the pivots read as artifacts and nothing materialized:

| after | resident |
| --- | --- |
| the interpreter | 0.15 GiB |
| the corpus is open | 1.09 GiB |
| the pivots are published | 1.22 GiB |
| the library is built (8 s) | 3.46 GiB |
| the index is built (57 s) | 7.28 GiB |

The last step adds 3.82 GiB for a table that is 1.19 GiB. Most of the difference is
DuckDB's own caches filling what `memory_limit` allows, and `Corpus` sets no limit, so
DuckDB takes its default share of whatever machine it finds — 19.1 GiB of this 24 GiB
laptop.

Constrain it and the build does not slow down; it stops:

| `memory_limit` | result | temporary files |
| --- | --- | --- |
| 4 GB | `OutOfMemoryException` after 64 s | — |
| 5 GB | built in 114 s | 15.79 GiB |
| 6 GB | built in 65 s | 16.10 GiB |
| 8 GB | built in 64 s | 25.28 GiB |

**Three remedies do not move the floor.** `preserve_insertion_order=false`, which is what
DuckDB's own error message suggests; a `temp_directory` to spill into, which does spill —
16 to 25 GiB of it — and still fails at 4 GB; and building the five indexed paths one at a
time with `INSERT` instead of one `UNION ALL`, which fails 33 s sooner because
`inputs.components` alone is 11.95M elements. The failure is "failed to pin block", and a
block that cannot be pinned is not one that can be spilled. The shape of the statement is
not what costs.

Two things follow for a deployment. The scratch requirement is the awkward one: a Fargate
task carries **20 GB** of ephemeral storage by default, so the configurations that
survive the memory floor are the ones that may not survive the disk. And the failure
arrives at the worst moment — the index is built by the first query that can spend it, so
a container short of the floor starts cleanly, passes `check_pivots()`, answers scalar
queries, and raises at whoever runs the first substructure search.

That last part is fixed rather than documented:
[ord-schema#969](https://github.com/open-reaction-database/ord-schema/pull/969) adds
`Corpus.check_index()`, the sibling of `check_pivots()`, so the refusal lands on a
deployment instead of on a request.

### 17. Chunking the build lowers the floor and is still not worth it

The lever finding 16 left open — building per *projection file* rather than per path, so
one file goes through the unnest instead of 2.4M reactions — works. It is also the fourth
remedy tried and the first that does anything, which is why it was worth trying: the
three before it all left the whole corpus in flight.

| `memory_limit` | one statement | per projection file |
| --- | --- | --- |
| 1 GB | fails | fails |
| 2 GB | fails | **166 s**, 9.05 GiB spilled |
| 4 GB | fails | **134 s**, 7.84 GiB spilled |
| 5 GB | 114 s, 15.79 GiB spilled | — |
| 6 GB | 65 s, 16.10 GiB spilled | — |

The floor drops from about 5 GB to about 2 GB and the spill roughly halves. Both shapes
produce 18,847,978 rows reaching exactly 2,016,224 distinct structures — the corpus
total, which is the invariant the build already asserts, so the per-file offsets are right
rather than merely row-count-equal.

Then the configuration most deployments actually run, with nothing constrained:

| at DuckDB's default 19.1 GiB | time | table | process | spilled |
| --- | --- | --- | --- | --- |
| one statement | 57 s | 1.17 GiB | 8.03 GiB | 6.37 GiB |
| per projection file | 96 s | 1.57 GiB | 10.50 GiB | 0.00 GiB |

Chunked is 68% slower, holds 2.5 GiB more, and leaves a 34% larger table — 265 separate
inserts store less compactly than one scan, and it costs *more* memory precisely because
it never has to spill.

**So: leave the build alone.** Chunking rescues a container below the floor by penalizing
every deployment above it, and the container it rescues is one finding 7 already argues
against — Fargate memory is among the cheapest RAM in AWS, and this workload wants ~8 GB
for the library and the index whatever the build does. Sizing the task correctly is
cheaper than making every startup slower.

What changes that: a deployment target capped below ~5 GB that cannot be raised. Chunking
is measured and correct, and would go in as a fallback after `OutOfMemoryException`
rather than as the default path.

### 18. Across a mixed workload the index is 2–24× ahead, and the gap is where the other clause is cheap

Finding 15 compared the routes on four structure queries. The shape a deployment actually
serves is a structure clause paired with one the index cannot carry, so the same
comparison was run over ten of those, warm, with the pivots read as artifacts and the
default budget. The second column refuses the index, which is where a corpus without one
lands — the pivots take every quantifier rather than the elements:

| query | index | pivots alone |
| --- | --- | --- |
| pyridine solvent, above 350 K | 0.020 s | 0.484 s |
| pyridine solvent, yield > 50% | 0.033 s | 0.105 s |
| pyridine solvent, white product | 0.028 s | 0.101 s |
| pyridine solvent, "reflux" in the procedure | 0.054 s | 0.493 s |
| yields by product color (grouped) | 0.036 s | 0.104 s |
| hottest with a yield (ordered, limited) | 0.033 s | 0.105 s |
| boronic acid, pyridine solvent, yield > 50% | 0.041 s | 0.142 s |
| any aromatic carbon, yield > 50% | 0.153 s | 0.259 s |
| a benzene ring, yield > 50% | 0.142 s | 0.241 s |
| **not** pyridine anywhere, with a yield | 0.123 s | 0.218 s |

Same answers on both routes. The gap is widest where the *other* clause is cheap — a
scalar path, or a substring — because there the whole query is the structure clause and
the index is answering all of it. Where the other clause is itself a quantifier a pivot
answers, the two converge to within about 3×, since both routes are then paying for the
same pivot semi-join.

This does not change finding 15's conclusion; it widens the evidence under it from four
queries of one shape to ten of the shape a server sees.

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

The pivot shipped as `ord_schema.artifacts.pivot` in
[ord-schema#965](https://github.com/open-reaction-database/ord-schema/pull/965); the
design and the implementation plan are kept beside this entry as
[the design](assets/pivoted-element-index-design.md)
and [the plan](assets/pivoted-element-index-plan.md).
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

**Build cost is depth; size saving is width.** The question this entry left unmeasured
turned out to have two answers rather than one, and reading it as one was wrong: an
early partial run said "minutes per level", which is true of a deep pivot and false of a
shallow one. Measured one build per process, so eviction cannot corrupt the memory delta
a build is read from, beside the top-level column a query would otherwise materialize
(GiB):

| level | unnests | pivot | build | column | | build |
| --- | --- | --- | --- | --- | --- | --- |
| `workups` | 1 | 4.40 | 42 s | `workups` | 5.20 | 3.3 s |
| `outcomes.products` | 2 | 0.45 | 461 s | `outcomes` | 3.23 | 4.1 s |
| `inputs.components` | 2 | 2.75 | 626 s | `inputs` | 4.05 | 2.5 s |
| `outcomes.products.measurements` | 3 | 1.61 | 854 s | `outcomes` | 3.23 | 4.1 s |

One unnest is 42 seconds, and each further repeated level costs roughly an order of
magnitude, where materializing a column is 2.5–4.1 s whatever it holds. Independently of
that, how much a pivot saves depends on how much of its column an element still carries
once the repeated fields are pruned away: **86%** for `outcomes.products`, **15%** for
`workups`, whose elements carry a whole `ReactionInput` besides. That 4.40 GiB exceeds
the 4 GiB default budget, so it is refused and the projection answers.

The two do not line up, which is what makes this worth stating separately. `workups` is
the cheapest pivot to build and the worst on size; `outcomes.products` is the opposite.
So deriving pivots offline is a strong argument for deep levels and nearly a moot one
for shallow ones — and the wide ones are the reason to derive *all* of them, since
findings 11 through 14 show the width stops costing anything the moment a pivot is a
file rather than a table.

### Still open

1. **Measure a genuinely cold read from real S3**, which finding 6 could not produce.
   Deferred deliberately: everything above is local, and the artifact sizes are small
   enough that the cold path is the only remaining unknown.
2. **Decide whether the column-set path stays at all.** Finding 10 settles the mechanism
   but not the design. With the footers held, a materialized column set is worth 25–65 ms
   for 1.5+ GB apiece and a 1.2–2.6 s stall on the query that builds it. The budget, LRU,
   eviction, and refusal machinery in
   [ord-schema#964](https://github.com/open-reaction-database/ord-schema/pull/964) is
   still needed by the pivots, which are worth seconds — so the question is whether
   `_narrowed_table` and its second compile pass earn their place, not whether the cache
   does.
3. **Derive a serialized `SubstructLibrary`** as an artifact too, so the ~1.5 GiB that
   pins a resident process is loaded rather than built. This is now the *largest*
   remaining resident cost by a wide margin: with the pivots on disk and the footers at
   200 MB, the library is most of the floor.
4. **Consider deriving a missing pivot to disk rather than to memory.** A corpus given a
   `pivots_dir` with no artifacts for a level builds that level in process, at up to
   4.18 GiB and 14 minutes. Writing it to the same directory instead would cost the same
   minutes once, no memory, and leave a real artifact behind for the next process. It
   turns `pivots_dir` from read-only into a cache, which is a semantic change worth
   deciding on rather than assuming.

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
- Scripts: [`assets/`](assets/)
- [Streamlining access to tabular datasets stored in Amazon S3 Tables with DuckDB](https://aws.amazon.com/blogs/storage/streamlining-access-to-tabular-datasets-stored-in-amazon-s3-tables-with-duckdb/)
  — AWS Storage Blog, the S3 Tables walkthrough assessed in finding 8
