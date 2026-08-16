# Copyright 2026 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Measure what a punctuation fold recovers over plain lowercasing.

PubChem's REST name lookup normalizes more than case: `N,N′-carbonyldiimidazole` with a
U+2032 PRIME resolves through the service but misses an index keyed on the lowercased
string, because the bulk synonym file spells that name with an ASCII apostrophe. Typed
and copy-pasted chemistry is full of these — primes, curly quotes, en dashes.

Queries each ORD name twice, plain-lowercased and folded, and reports what the second
form adds. Also counts how many index keys carry a foldable character themselves, since
those are unreachable from an ASCII query however the query is spelled.

Usage: normalize_gap.py INDEX_DIR TESTSET
"""

import argparse
import csv
import pathlib
import unicodedata

import duckdb

# Characters that are the same character for naming purposes. Greek letters are left
# alone: alpha and a are not interchangeable in a chemical name.
FOLD = str.maketrans(
    {
        "′": "'", "″": '"', "‘": "'", "’": "'", "“": '"', "”": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
        " ": " ", "​": "",
    }
)
FOLDABLE = "[′″‘’“”‐‑‒–—− ​]"


def fold(name: str) -> str:
    """Returns ``name`` lowercased with lookalike punctuation mapped to ASCII."""
    return unicodedata.normalize("NFKC", name).translate(FOLD).lower().strip()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("index_dir", type=pathlib.Path)
parser.add_argument("testset", type=pathlib.Path)
args = parser.parse_args()

with args.testset.open() as handle:
    testset = list(csv.DictReader(handle, delimiter="\t"))
counts = {row["name"]: int(row["rows"]) for row in testset}

con = duckdb.connect(database=":memory:")
con.execute(
    "CREATE VIEW idx AS SELECT * FROM "
    f"read_parquet('{args.index_dir / 'pubchem_names.parquet'}')"
)
con.execute("CREATE TABLE probe (name VARCHAR, plain VARCHAR, folded VARCHAR)")
con.executemany(
    "INSERT INTO probe VALUES (?, ?, ?)",
    [(row["name"], row["name"].lower().strip(), fold(row["name"])) for row in testset],
)

results = {
    key: dict(
        con.execute(
            f"SELECT p.name, i.smiles FROM probe p JOIN idx i ON i.name = p.{key}"
        ).fetchall()
    )
    for key in ("plain", "folded")
}
for key, hits in results.items():
    rows = sum(counts[name] for name in hits)
    print(f"{key:<7} {len(hits):>6,} names  {rows:>7,} rows")

gained = set(results["folded"]) - set(results["plain"])
print(f"\ngained by folding: {len(gained)} names, {sum(counts[n] for n in gained):,} rows")
for name in sorted(gained, key=lambda n: -counts[n])[:15]:
    print(f"  {counts[name]:>6} {name!r} -> {results['folded'][name][:50]}")

unreachable = con.execute(
    f"SELECT count(*) FROM idx WHERE regexp_matches(name, '{FOLDABLE}')"
).fetchone()[0]
print(f"\nindex keys containing a foldable character: {unreachable:,}")
