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

"""Profile what is actually in the index, and what a slimmed-down index would cost.

Most PubChem synonyms are machine identifiers — vendor catalog codes, InChIKeys,
depositor accessions — not names anyone types or records in a reaction. Dropping them
is the obvious way to make the artifact shippable, so this measures both halves of that
trade: how much of the index each class of identifier accounts for, and whether any ORD
name-only name would be lost by excluding it.

Usage: analyze_index.py INDEX_DIR TESTSET OUT_DIR
"""

import argparse
import csv
import pathlib
import sqlite3
import time

import duckdb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("index_dir", type=pathlib.Path)
parser.add_argument("testset", type=pathlib.Path)
parser.add_argument("out_dir", type=pathlib.Path)
args = parser.parse_args()
parquet_path = args.index_dir / "pubchem_names.parquet"
slim_path = args.out_dir / "pubchem_names_slim.parquet"
slim_sqlite = args.out_dir / "pubchem_names_slim.sqlite"

# A name is "machine" if it is one of these. Each pattern is anchored, so a real name
# that merely contains a code (e.g. "zinc chloride") is unaffected.
CLASSES = {
    "InChIKey": r"^[a-z]{14}-[a-z]{10}-[a-z]$",
    "CAS-like registry number": r"^[0-9]{2,7}-[0-9]{2}-[0-9]$",
    # Prefixes are anchored to a digit wherever the letters alone could begin a real
    # name: "zinc chloride" is a reagent, "zinc000012345" is a catalog number, and
    # "s1p" is sphingosine-1-phosphate while "s1234" is a Selleck code.
    "vendor/database accession": (
        r"^(schembl|zinc[0-9]|akos|mfcd|chembl[0-9]|dtxsid|dtxcid|chebi:|hms[0-9]|"
        r"mls[0-9]|smr[0-9]|ncgc[0-9]|nsc[0-9]|bdbm|stk[0-9]|en300|s[0-9]{4,}|cs-[0-9]|"
        r"ab[0-9]{5,}|bs-[0-9]|hy-[0-9]|ft-[0-9]|gtpl[0-9]|unii-|sr-[0-9]|tox21_|"
        r"bcp[0-9]|db[0-9]{5}|q[0-9]{5,}|opera_|amy[0-9]|a[0-9]{6,}|cid[ _]?[0-9])"
    ),
    "UNII-style 10-char code": r"^[0-9][0-9a-z]{9}$",
    "SMILES-looking string": r"^[^a-z]*$",
}

con = duckdb.connect(database=":memory:")
con.execute("SET memory_limit='12GB'")
con.execute(f"SET temp_directory='{args.out_dir / 'duckdb_tmp'}'")
con.execute(f"CREATE VIEW idx AS SELECT * FROM read_parquet('{parquet_path}')")

total = con.sql("SELECT count(*) FROM idx").fetchone()[0]
print(f"indexed names {total:,}")

ambiguous = con.sql("SELECT count(*) FROM idx WHERE n_cids > 1").fetchone()[0]
print(f"names matching >1 CID {ambiguous:,} ({ambiguous / total:.1%})")

print()
print("composition (each class counted independently; classes overlap):")
for label, pattern in CLASSES.items():
    count = con.execute(
        f"SELECT count(*) FROM idx WHERE regexp_matches(name, '{pattern}')"
    ).fetchone()[0]
    print(f"  {label:<28} {count:>13,} ({count / total:>5.1%})")

machine = " OR ".join(f"regexp_matches(name, '{p}')" for p in CLASSES.values())
kept = con.execute(f"SELECT count(*) FROM idx WHERE NOT ({machine})").fetchone()[0]
print(f"  {'kept by a slim index':<28} {kept:>13,} ({kept / total:>5.1%})")

with args.testset.open() as handle:
    names = [row["name"].lower() for row in csv.DictReader(handle, delimiter="\t")]
con.execute("CREATE TABLE probe (name VARCHAR)")
con.executemany("INSERT INTO probe VALUES (?)", [(name,) for name in names])
lost = con.execute(
    f"""
    SELECT count(*) FROM probe p JOIN idx i USING (name) WHERE {machine}
    """
).fetchone()[0]
print(f"\nORD name-only names that a slim index would drop: {lost}")
if lost:
    for (name,) in con.execute(
        f"SELECT p.name FROM probe p JOIN idx i USING (name) WHERE {machine} LIMIT 20"
    ).fetchall():
        print(f"  {name!r}")

start = time.monotonic()
con.execute(
    f"""
    COPY (SELECT name, smiles, cid, n_cids FROM idx WHERE NOT ({machine}) ORDER BY name)
    TO '{slim_path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)
    """
)
print(f"\nslim parquet written in {time.monotonic() - start:.1f}s")

start = time.monotonic()
slim_sqlite.unlink(missing_ok=True)
sqlite_con = sqlite3.connect(slim_sqlite)
sqlite_con.executescript(
    "PRAGMA journal_mode=off; PRAGMA synchronous=off;"
    "CREATE TABLE name_smiles (name TEXT PRIMARY KEY, smiles TEXT NOT NULL,"
    " cid INTEGER NOT NULL, n_cids INTEGER NOT NULL) WITHOUT ROWID;"
)
reader = con.execute(
    f"SELECT name, smiles, cid, n_cids FROM read_parquet('{slim_path}')"
)
while batch := reader.fetchmany(1_000_000):
    sqlite_con.executemany("INSERT INTO name_smiles VALUES (?, ?, ?, ?)", batch)
sqlite_con.commit()
sqlite_con.close()
print(f"slim sqlite written in {time.monotonic() - start:.1f}s")

print(f"full parquet {parquet_path.stat().st_size:>13,} bytes")
print(f"slim parquet {slim_path.stat().st_size:>13,} bytes")
print(f"slim sqlite  {slim_sqlite.stat().st_size:>13,} bytes")
