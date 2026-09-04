# DateTime format extracts

- **Date:** 2026-09-03
- **Author:** Steven Kearnes
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Supporting files for
[`2026-09-03-date-time-formats/`](../../2026-09-03-date-time-formats/README.md).

## Files

- `mini_reaction.py` — a cut-down `Reaction` proto holding only the seven paths
  that reach a `DateTime`, built from `descriptor_pb2` at import. Everything
  else in the wire format becomes an unknown field the parser skips, which is
  what makes a full-corpus scan affordable. Imported by both scripts; not run on
  its own.
- `scan_date_times.py` — walks every dataset, reduces each `DateTime` value to a
  format signature, and writes one row per (dataset, schema position,
  signature). Produces `date_time_formats.csv`.
- `resolve_orientation.py` — decides day-first versus month-first for the
  slash-separated values, from confirmations recorded in `_CONFIRMED`,
  witnesses, upper bounds, co-submitted siblings, the `en-US` 12-hour format,
  and finally proximity. Produces `slash_orientation.csv`.
- `preview_normalization.py` — dry-runs the entry's normalization proposal:
  parses every value with an explicit `strptime` format chosen from its
  signature and the recorded day/month order, re-emits it as ISO 8601, and
  prices the three candidate scopes (`all`, `slash`, `ambiguous`) in files,
  bytes, reactions and values. It also checks the claim the recommended scope
  rests on — that every slash value left behind reads correctly with no
  per-dataset knowledge — and exits non-zero if any does not. Writes nothing,
  skips any dataset whose order is still open, and raises on a value it cannot
  read.
- `date_time_formats.csv` — 176 rows: `dataset_id`, `position`, `signature`,
  `count`, `example`. A signature is the value with digit runs replaced by runs
  of `N`, month and weekday names by `MON` and `DAY`, `AM`/`PM` by `AP`, and
  every other word by `W`; separators and field widths are kept, so two values
  share a signature exactly when they share a format.
- `slash_orientation.csv` — 48 rows, one per (dataset, position) holding slash
  values: the witness counts in each direction, the upper bound, the latest
  timestamp each reading implies, the verdict, and which kind of evidence
  settled it. A verdict ending in `(lean)` is proximity only and is not a
  finding: the two that remain are with their submitters.

## Reproducing

Needs `pyarrow`, `protobuf`, and an `ord-data` checkout with its Git LFS objects
materialized. Both scripts read that checkout; `resolve_orientation.py` also
reads its git history, so a full clone is required, not a shallow one.

```bash
python scan_date_times.py \
  --data_directory /path/to/ord-data/data \
  --output date_time_formats.csv

python resolve_orientation.py \
  --repository /path/to/ord-data \
  --output slash_orientation.csv

python preview_normalization.py \
  --data_directory /path/to/ord-data/data \
  --orientations slash_orientation.csv
```

Each takes a few minutes over the full corpus, dominated by
`ord_dataset-1158e351…` (USPTO grants, 1,771,032 of the 2,428,291 reactions).

The extracts here were produced from ord-data at
[`83f971f`](https://github.com/Open-Reaction-Database/ord-data/commit/83f971f).
`resolve_orientation.py` bounds values against commit dates, so re-running it on
a later checkout can shift a `bound` column without changing a verdict.
