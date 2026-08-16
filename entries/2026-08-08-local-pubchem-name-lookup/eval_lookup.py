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

"""Score the local index against the ORD name-only set and the live PubChem API.

Three questions:

1. Coverage — of the 46,831 candidate names (and the ORD rows they sit on), how many
   does the local index answer, split by what the 2026-07-11 pass already resolved.
2. Agreement — on the names probed against live PUG REST, does the local index return
   the same structure? Compared as RDKit canonical SMILES, which is what
   `resolvers.canonicalize_smiles` writes, so two spellings of one molecule count as
   agreement and a different molecule does not.
3. Latency — single lookups against SQLite and against DuckDB/Parquet, cold and warm,
   plus whole-set batch throughput.

Usage: eval_lookup.py INDEX_DIR TESTSET API_PROBE OUT_PREFIX
"""

import argparse
import csv
import pathlib
import sqlite3
import statistics
import subprocess
import time

import duckdb
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("index_dir", type=pathlib.Path)
parser.add_argument("testset", type=pathlib.Path)
parser.add_argument("api_probe", type=pathlib.Path)
parser.add_argument("out_prefix", type=pathlib.Path)
args = parser.parse_args()

parquet_path = args.index_dir / "pubchem_names.parquet"
sqlite_path = args.index_dir / "pubchem_names.sqlite"

with args.testset.open() as handle:
    testset = list(csv.DictReader(handle, delimiter="\t"))
names = [row["name"] for row in testset]


def canonical(smiles: str) -> str | None:
    """Returns RDKit canonical SMILES, or None if it will not parse."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol is not None else None


# --- 1. Coverage -------------------------------------------------------------------
con = duckdb.connect(database=":memory:")
con.execute("CREATE TABLE probe (name VARCHAR)")
con.executemany("INSERT INTO probe VALUES (?)", [(name,) for name in names])
start = time.monotonic()
hits = dict(
    con.execute(
        f"""
        SELECT p.name, i.smiles
        FROM probe p JOIN read_parquet('{parquet_path}') i ON lower(p.name) = i.name
        """
    ).fetchall()
)
batch_seconds = time.monotonic() - start

with (args.out_prefix.with_name(args.out_prefix.name + "_local_hits.tsv")).open(
    "w", newline=""
) as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["name", "rows", "prior", "smiles"])
    for row in testset:
        writer.writerow([row["name"], row["rows"], row["prior"], hits.get(row["name"], "")])

print("== coverage (46,831 candidate names from 2026-07-11)")
print(f"batch lookup of {len(names):,} names: {batch_seconds:.2f}s")
buckets: dict[str, list[tuple[int, bool]]] = {}
for row in testset:
    buckets.setdefault(row["prior"], []).append(
        (int(row["rows"]), row["name"] in hits)
    )
for prior, entries in sorted(buckets.items()):
    hit_names = sum(1 for _, hit in entries if hit)
    hit_rows = sum(count for count, hit in entries if hit)
    all_rows = sum(count for count, _ in entries)
    print(
        f"  prior={prior:<5} names {hit_names:>6,}/{len(entries):<6,} "
        f"({hit_names / len(entries):>5.1%})   rows {hit_rows:>7,}/{all_rows:<7,} "
        f"({hit_rows / all_rows:>5.1%})"
    )
total_rows = sum(int(row["rows"]) for row in testset)
hit_rows = sum(int(row["rows"]) for row in testset if row["name"] in hits)
print(
    f"  {'total':<11} names {len(hits):>6,}/{len(testset):<6,} "
    f"({len(hits) / len(testset):>5.1%})   rows {hit_rows:>7,}/{total_rows:<7,} "
    f"({hit_rows / total_rows:>5.1%})"
)

# --- 2. Agreement with the live API ------------------------------------------------
with args.api_probe.open() as handle:
    probe = list(csv.DictReader(handle, delimiter="\t"))
agree = disagree = api_only = local_only = both_miss = unparseable = 0
disagreements = []
for row in probe:
    api = canonical(row["smiles"])
    local = canonical(hits.get(row["name"], ""))
    if row["smiles"] and api is None:
        unparseable += 1
    if api and local:
        if api == local:
            agree += 1
        else:
            disagree += 1
            disagreements.append((row["name"], api, local))
    elif api:
        api_only += 1
    elif local:
        local_only += 1
    else:
        both_miss += 1
print()
print(f"== agreement on {len(probe)} names probed against live PUG REST")
print(f"  both answered, same structure   {agree}")
print(f"  both answered, different        {disagree}")
print(f"  API only                        {api_only}")
print(f"  local only                      {local_only}")
print(f"  neither                         {both_miss}")
print(f"  API answer RDKit could not read {unparseable}")
for name, api, local in disagreements[:20]:
    print(f"    {name!r}\n      api   {api}\n      local {local}")

# --- 3. Latency --------------------------------------------------------------------
sample = [name for name in names if name in hits][:500]


def time_lookups(fn, values):
    """Returns per-call milliseconds for each value in ``values``."""
    out = []
    for value in values:
        start = time.monotonic()
        fn(value)
        out.append((time.monotonic() - start) * 1000)
    return out


def report(label, timings):
    timings = sorted(timings)
    print(
        f"  {label:<28} p50 {timings[len(timings) // 2]:>7.3f} ms   "
        f"p95 {timings[int(len(timings) * 0.95)]:>7.3f} ms   "
        f"mean {statistics.mean(timings):>7.3f} ms"
    )


print()
print("== single-lookup latency")
subprocess.run(["sync"], check=True)
sqlite_con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
query = "SELECT smiles FROM name_smiles WHERE name = ?"
cold = time_lookups(lambda v: sqlite_con.execute(query, (v.lower(),)).fetchone(), sample[:50])
print(f"  sqlite first lookup          {cold[0]:.3f} ms")
report("sqlite (warm)", time_lookups(
    lambda v: sqlite_con.execute(query, (v.lower(),)).fetchone(), sample))

duck = duckdb.connect(database=":memory:")
duck.execute(f"CREATE VIEW idx AS SELECT * FROM read_parquet('{parquet_path}')")
parquet_query = "SELECT smiles FROM idx WHERE name = ?"
first = time_lookups(lambda v: duck.execute(parquet_query, [v.lower()]).fetchone(), sample[:1])
print(f"  duckdb first lookup          {first[0]:.3f} ms")
report("duckdb/parquet (warm)", time_lookups(
    lambda v: duck.execute(parquet_query, [v.lower()]).fetchone(), sample))
