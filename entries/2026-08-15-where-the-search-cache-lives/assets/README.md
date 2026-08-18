# Scripts for "Where the agent search cache can live"

- **Date:** 2026-08-15
- **Author:** Steven Kearnes
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Measurement probes for
[`2026-08-15-where-the-search-cache-lives/`](../../2026-08-15-where-the-search-cache-lives/README.md).

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
| `probe_cache.py` | four cache configurations over the projections, raw DuckDB | 10 |
| `probe_footer.py` | the same question through a real `Corpus`, with and without materialization | 10 |
| `probe_struct_pushdown.py` | whether a scan pays for struct fields it does not name | 11 |
| `probe_width.py` | where the bytes sit inside each level, read from the footers | 12 |
| `probe_element.py` | what each field of a pivot's element costs in memory | 13 |
| `derive_probe_pivots.py` | derives the pivot artifacts the route benchmark reads | 14 |
| `bench_artifacts.py` | pivots as artifacts, against in memory, against the elements | 14 |
| `probe_subsume.py` | structure queries on the index, the pivots, and the elements | 15 |
| `probe_floor.py` | process residency of each startup step, at three DuckDB limits | 16 |
| `probe_index_limit.py` | where the index build's memory floor sits, and what it spills | 16 |
| `probe_index_shape.py` | whether building the index path by path lowers that floor | 16 |
| `probe_index_chunked.py` | the same build one projection file at a time | 17 |
| `probe_index_default.py` | both build shapes where nothing is constrained | 17 |
| `bench_mixed.py` | a mixed workload on the index, against the pivots alone | 18 |
| `probe_cgroup.py` | what DuckDB's defaults become inside a memory-capped container | 19 |
| `probe_container_index.py` | the index build under that cap, and which way it ends | 19 |

The last two run in Docker rather than on the host, since a cgroup cap is the thing they
measure; each script's docstring carries the command. Give the spill directory a volume
rather than a bind mount — a build that fills 25 GB of temporary files through one takes
longer to delete them than to run.

`probe_width.py` reads only Parquet footers, so it is the one script here that finishes in
seconds. `probe_element.py` builds all four pivots and takes about 40 minutes;
`derive_probe_pivots.py` and `bench_artifacts.py` together take a couple of hours.

`derive_probe_pivots.py` stubs out the staleness check, because the local projections were
written by an older `ord_schema` than the one installed and `write_pivot` refuses a stale
parent. That is correct behavior being worked around for a measurement, not a suggestion:
the corpus it feeds is opened with `require_current=False` and nothing it writes ships.

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
