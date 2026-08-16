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

"""Measure what ChEMBL adds to a PubChem-derived name index.

PubChem ingests ChEMBL as a depositor, so the prior is that ChEMBL contributes little to
a name -> structure map built from PubChem. This checks it directly: pull
`molecule_synonyms` joined to `compound_structures` out of the ChEMBL SQLite release,
normalize names the same way `build_index.py` does, and ask two questions — how many
ChEMBL names the PubChem index already answers, and how many ORD name-only names ChEMBL
would resolve that PubChem cannot.

Usage: chembl_overlap.py CHEMBL_SQLITE INDEX_DIR TESTSET
"""

import argparse
import csv
import gzip
import pathlib
import sqlite3

import duckdb
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("chembl_sqlite", type=pathlib.Path)
parser.add_argument("index_dir", type=pathlib.Path)
parser.add_argument("testset", type=pathlib.Path)
args = parser.parse_args()

chembl = sqlite3.connect(f"file:{args.chembl_sqlite}?mode=ro", uri=True)
rows = chembl.execute(
    """
    SELECT DISTINCT lower(trim(s.synonyms)), c.canonical_smiles
    FROM molecule_synonyms s
    JOIN compound_structures c USING (molregno)
    WHERE s.synonyms IS NOT NULL AND c.canonical_smiles IS NOT NULL
    UNION
    SELECT DISTINCT lower(trim(m.pref_name)), c.canonical_smiles
    FROM molecule_dictionary m
    JOIN compound_structures c USING (molregno)
    WHERE m.pref_name IS NOT NULL AND c.canonical_smiles IS NOT NULL
    """
).fetchall()
# One name can carry several ChEMBL structures; keep the first, as the PubChem index
# keeps the lowest CID, so the comparison is like for like.
chembl_names: dict[str, str] = {}
for name, smiles in rows:
    chembl_names.setdefault(name, smiles)
print(f"ChEMBL synonym rows {len(rows):,} -> {len(chembl_names):,} unique names")

con = duckdb.connect()
con.execute("SET memory_limit='8GB'")
con.execute(
    "CREATE VIEW idx AS SELECT * FROM "
    f"read_parquet('{args.index_dir / 'pubchem_names.parquet'}')"
)
con.execute("CREATE TABLE chembl (name VARCHAR, smiles VARCHAR)")
con.executemany("INSERT INTO chembl VALUES (?, ?)", list(chembl_names.items()))

covered = con.execute(
    "SELECT count(*) FROM chembl c JOIN idx i USING (name)"
).fetchone()[0]
print(
    f"ChEMBL names the PubChem index already has: {covered:,} "
    f"({covered / len(chembl_names):.1%})"
)

opener = gzip.open if args.testset.suffix == ".gz" else open
with opener(args.testset, mode="rt") as handle:
    testset = list(csv.DictReader(handle, delimiter="\t"))
con.execute("CREATE TABLE probe (name VARCHAR, rows_ INTEGER)")
con.executemany(
    "INSERT INTO probe VALUES (?, ?)",
    [(row["name"].lower(), int(row["rows"])) for row in testset],
)

added = con.execute(
    """
    SELECT p.name, c.smiles, p.rows_
    FROM probe p JOIN chembl c USING (name)
    WHERE p.name NOT IN (SELECT name FROM idx)
    ORDER BY p.rows_ DESC
    """
).fetchall()
print(
    f"\nORD names ChEMBL resolves that the PubChem index cannot: {len(added)} "
    f"({sum(row[2] for row in added):,} rows)"
)
for name, smiles, count in added[:25]:
    print(f"  {count:>5} {name[:44]:<46} {smiles[:44]}")

# Where both answer, do they answer the same thing?
both = con.execute(
    """
    SELECT p.name, i.smiles, c.smiles
    FROM probe p JOIN idx i USING (name) JOIN chembl c ON c.name = p.name
    """
).fetchall()


def canonical(smiles: str) -> str | None:
    """Returns RDKit canonical SMILES, or None if it will not parse."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol is not None else None


differ = [(n, a, b) for n, a, b in both if canonical(a) != canonical(b)]
print(f"\nORD names both resolve: {len(both)}; different structure: {len(differ)}")
for name, pubchem, chembl_smiles in differ[:10]:
    print(f"  {name!r}\n    pubchem {pubchem[:60]}\n    chembl  {chembl_smiles[:60]}")
