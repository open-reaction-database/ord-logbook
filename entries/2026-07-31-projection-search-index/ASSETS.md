# Measurement scripts

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Scripts behind [2026-07-31 does the projection need a search index?](../2026-07-31-projection-search-index/README.md).

| script | produces |
| --- | --- |
| `component_facts.py` | the flat component fact table — 17,021,402 rows, 186.2 MB, 8.7 min (finding 3) |
| `queries.sql` | the query pairs behind findings 1–3, each written both ways |
| `total_eav.py` | one row per populated leaf over the whole proto, with a positional `entity_key` (summary, D2). Un-normalized — a normalized version is the missing measurement |

`component_facts.py` reads source protos through `parquet.iter_reactions` and writes a
single Parquet file; it does not read the nested projection (finding 4). Point the glob
at an `ord-data` checkout and adjust the output path at the top before running.

The nested projection those queries run against comes from `normalized_projection.py` in
[the previous entry's assets](../2026-07-30-agent-access-sidecars-or-orm/ASSETS.md).

Timings are single-process on an Apple silicon laptop, DuckDB 1.5.5, cold. They are
meaningful as ratios between query formulations and between artifacts, rather than as
absolute figures.
