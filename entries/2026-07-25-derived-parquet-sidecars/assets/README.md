# Facts-tier derivation measurements

Supporting files for [`entries/2026-07-25-derived-parquet-sidecars.md`](../../2026-07-25-derived-parquet-sidecars/README.md).

## Files

- `derive_facts.py` — builds a tier-1 sidecar from a source Parquet dataset and reports
  bytes, row counts, SMILES coverage, and wall-clock as JSON. Writes two column sets so
  the marginal cost of per-component SMILES is visible separately (`core` without,
  `full` with). The `full` set is what the entry treats as shipping.
- `results.jsonl` — one JSON object per dataset from the run described below: the 52
  non-USPTO parquet datasets, derived in full.

## Reproducing

Needs `ord-schema` (with RDKit) and `pyarrow`, and a checkout of `ord-data` with its
Git LFS objects materialized.

```bash
cd /path/to/ord-data
for p in $(find data -name '*.parquet' | sort); do
  case "$p" in *1158e351*) continue;; esac   # USPTO: sampled separately, see below
  python derive_facts.py "$p" --out-dir /tmp/out --generate
done
```

`uspto-grants` (`ord_dataset-1158e351757f315b93cbcbe7bc55f38e`) is 1.77M reactions and
was sampled rather than derived in full:

```bash
python derive_facts.py \
  data/11/ord_dataset-1158e351757f315b93cbcbe7bc55f38e.parquet \
  --out-dir /tmp/out --generate --max-row-groups 200
```

`--max-row-groups` selects evenly-spaced row groups rather than a leading prefix,
because USPTO's row groups are in source order; results are extrapolated by row count.
The USPTO figures in the entry therefore carry that caveat, and its row is marked
*(sampled)* wherever it appears.

## Numbers not in `results.jsonl`

Two measurements in the entry were computed from the derived output files rather than
from this script, and are reproducible from `/tmp/out/*.full.parquet` with `pyarrow`:

- **Per-column byte shares** (finding 9) — sum `total_compressed_size` per column across
  every row group. Also confirms `is_stats_set` on all column chunks, which is what
  makes row-group pruning work without a compacted artifact.
- **Yield distribution near zero** (D2) — null count plus counts under 0, 1, 5, and 10
  percent, which is the evidence that a negative-result threshold is contested.
