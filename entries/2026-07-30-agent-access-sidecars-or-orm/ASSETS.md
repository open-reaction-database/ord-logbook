# Measurement scripts

Scripts behind [2026-07-30 unlocking agents](../2026-07-30-agent-access-sidecars-or-orm/README.md).

They read the tier-1 views produced by `ord_schema.views.write_view`
([ord-schema#914](https://github.com/open-reaction-database/ord-schema/pull/914)), so
generate those first:

```bash
python -m ord_schema.scripts.derive_views \
  --input_pattern="/path/to/ord-data/data/*/*.parquet" \
  --output_dir=/tmp/views
```

Each script has the views directory and its scratch paths hard-coded at the top; point
them at `/tmp/views` before running. Run them from an environment with `ord-schema`,
`numpy`, and `duckdb` installed.

| script | produces |
| --- | --- |
| `distinct_structures.py` | distinct component SMILES count (finding 3); writes the SMILES list the other two structure scripts consume |
| `substructure_scan.py` | pattern-fingerprint screen and verify timings (finding 3) |
| `similarity_scan.py` | Morgan build time, Tanimoto scan time, structure-sidecar sizing (findings 3 and 4) |
| `sqlite_comparison.py` | SQLite package size, build time, and query timings against the same data (finding 6) |
| `total_projection.py` | descriptor-driven projection of the entire `Reaction` proto into nested Parquet, with size and conversion timings (finding 2) |
| `normalized_projection.py` | the same projection with united messages converted to canonical floats and structural identifiers collapsed to one `smiles` (finding 2b) |
| `identifier_census.py` | identifier-type distribution and how many compounds a full collapse would empty (finding 2b) |

`total_projection.py` takes a source dataset path and an optional row limit, and reads
the source parquet directly rather than the views:

```bash
python total_projection.py /path/to/ord-data/data/11/ord_dataset-1158e351....parquet 40000
```

`substructure_scan.py` and `similarity_scan.py` sample the first 100,000 distinct
structures and the entry projects to the full 1,432,318 by ratio; `sqlite_comparison.py`
loads the corpus in full.

Timings are single-process on an Apple silicon laptop and are meaningful as ratios
between formats rather than as absolute figures.
