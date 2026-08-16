"""Row coverage of the ORD name-only population, before and after the local index.

The 2026-07-11 pass resolved names with a curated dictionary and OPSIN, covering 10.0%
of the 864,997 name-only rows. This scores what the local PubChem index adds on top,
against the same denominator, so the two entries' headline numbers are comparable.

Usage: coverage_union.py LOCAL_HITS
"""

import argparse
import csv
import gzip
import pathlib

PRIOR = pathlib.Path("../2026-07-11-name-only-compounds")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("local_hits", type=pathlib.Path)
args = parser.parse_args()

counts: dict[str, int] = {}
for path, opener in (
    (PRIOR / "name_only_compounds.tsv.gz", gzip.open),
    (PRIOR / "name_only_product_compounds.tsv", open),
):
    with opener(path, mode="rt") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader)
        for count, name in reader:
            counts[name] = counts.get(name, 0) + int(count)
total_rows = sum(counts.values())

with (PRIOR / "combined_resolved.tsv").open() as handle:
    prior_names = {row["name"] for row in csv.DictReader(handle, delimiter="\t")}
with args.local_hits.open() as handle:
    local_names = {
        row["name"] for row in csv.DictReader(handle, delimiter="\t") if row["smiles"]
    }


def rows_for(names: set[str]) -> int:
    """Returns the number of ORD name-only rows carrying any of ``names``."""
    return sum(counts.get(name, 0) for name in names)


for label, names in (
    ("2026-07-11 (manual + OPSIN)", prior_names),
    ("local PubChem index", local_names),
    ("added by the index", local_names - prior_names),
    ("union", prior_names | local_names),
):
    rows = rows_for(names)
    print(f"{label:<28} {len(names):>6,} names  {rows:>7,} rows  ({rows / total_rows:>5.1%})")
print(f"{'denominator':<28} {len(counts):>6,} names  {total_rows:>7,} rows")
