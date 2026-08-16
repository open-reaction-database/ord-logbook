# Measurement scripts

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Scripts behind [2026-07-31 normalized EAV versus normalized projection](../../2026-07-31-eav-versus-projection/README.md).

| script | produces |
| --- | --- |
| `normalized_eav.py` | the normalized total EAV over the whole corpus — one row per populated leaf, carrying `path`, positional `entity_key`, and typed value columns (finding 9) |
| `interop.py` | nested-leaf access across DuckDB, pyarrow, polars, and pandas (finding 4) |

`normalized_eav.py` applies the same normalizations as the nested projection — united
messages to canonical floats, structural identifiers collapsed to one `smiles` — so the
two artifacts differ only in shape. It reads source protos through
`parquet.iter_reactions`; adjust the input glob and output path at the top.

The nested projection it is compared against comes from `normalized_projection.py` in
[the agent-access entry's assets](../../2026-07-30-agent-access-sidecars-or-orm/assets/); the
selection and wide-analysis timings come from the scripts in
[the search-index entry's assets](../../2026-07-31-projection-search-index/assets/).

Timings are single-process on an Apple silicon laptop and are meaningful as ratios
between shapes rather than as absolute figures.
