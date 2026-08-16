# Scripts for "Where the agent search cache can live"

Measurement probes for
[`entries/2026-08-15-where-the-search-cache-lives.md`](../../2026-08-15-where-the-search-cache-lives/README.md).

Each reads the local projection artifacts from `~/ord/projections/**/*.parquet` and writes
scratch databases under `/tmp`. They are measurement probes rather than library code: run
them in an environment with `duckdb` and `ord_schema` importable, and expect the pivot
builds to take about half an hour over the full corpus.

| script | what it measures | finding |
| --- | --- | --- |
| `probe_native.py` | the corpus as a native DuckDB file, at 2 GiB and 6 GiB memory limits | 4 |
| `probe_flat.py` | resident size of pivoted tables for four repeated paths | 1 |
| `probe_flat_query.py` | query latency against pivoted tables held in memory | 2 |
| `probe_flat_parquet.py` | the same queries read from Parquet, cold and warm, across memory limits | 3, 6 |
| `probe_flat_subset.py` | the same sizes from a row sample, as a cheap stand-in for the full build | 5 |

Beside them are the two documents the implementation was written from:
`pivoted-element-index-design.md`, which settles what a pivot holds and why, and
`pivoted-element-index-plan.md`, the task-by-task plan built from it. They live here
rather than in ord-schema because they describe a decision and its reasoning rather than
the code that resulted, which the repository already carries.

`probe_flat_subset.py` samples by row. It replaces an earlier version that sampled four
projection *directories*, which finding 5 describes: one directory holds 88% of this
corpus, so that version drew 1,486 of 2,428,291 reactions and its extrapolation was noise.

`probe_flat_query.py` writes `/tmp/ord_flat.duckdb`, which `probe_flat_parquet.py` then
exports to Parquet, so run them in that order. Both reuse their output if it already
exists; delete it to force a rebuild.

Sizes are reported in binary units (1024³ for GiB, 1024² for MiB). Resident size comes
from `duckdb_memory()` filtered to `tag = 'IN_MEMORY_TABLE'`, taken as a delta across each
`CREATE TABLE`.

`probe_native.py` leaves a 5.41 GiB database behind; delete `/tmp/ord_native.duckdb` when
finished with it.
