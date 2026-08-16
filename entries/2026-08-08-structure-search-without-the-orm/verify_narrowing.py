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

"""Does narrowing by the query's other predicates shrink the verification set?

Eager: verify every structure that survives the fingerprint screen.
Narrowed: verify only structures that survive the screen AND actually occur in an
element passing the query's other predicates.
"""

import multiprocessing as mp
import time

import duckdb
import numpy as np
import pyarrow as pa
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")
BITS = 2048
GLOB = "/Users/skearnes/ord/projections/*/*.parquet"
_QUERY = None


def _featurize(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    fp = Chem.PatternFingerprint(mol, fpSize=BITS)
    return smiles, np.packbits(
        np.frombuffer(fp.ToBitString().encode(), "u1") - ord("0")).tobytes()


def _init(smarts):
    global _QUERY
    _QUERY = Chem.MolFromSmarts(smarts)


def _match(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None and mol.HasSubstructMatch(_QUERY)


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{GLOB}', union_by_name=true)")
    con.execute("""
        CREATE TABLE component_view AS
        SELECT reaction_id, c.smiles AS smiles, c.reaction_role AS role,
               c.amount.volume_liters AS volume_liters,
               c.amount.moles_moles AS moles
        FROM (SELECT reaction_id, unnest(flatten(list_transform(map_values(inputs),
                     x -> x.components))) AS c FROM r)
        WHERE c.smiles IS NOT NULL
    """)
    smiles = [row[0] for row in
              con.execute("SELECT DISTINCT smiles FROM component_view").fetchall()]
    with mp.Pool(10) as pool:
        rows = [r for r in pool.map(_featurize, smiles, chunksize=500) if r]
    con.execute("DROP TABLE IF EXISTS structures")
    con.register("s_arrow", pa.table({
        "smiles": pa.array([r[0] for r in rows]),
        "pattern_fp": pa.array([r[1] for r in rows], type=pa.binary())}))
    con.execute("CREATE TABLE structures AS SELECT * FROM s_arrow")
    print(f"{len(rows)} distinct structures, "
          f"{con.execute('SELECT count(*) FROM component_view').fetchone()[0]} components\n")

    scenarios = [
        ("pyridine, unconstrained", "c1ccncc1", "TRUE"),
        ("pyridine, as SOLVENT", "c1ccncc1", "role = 'SOLVENT'"),
        ("pyridine, SOLVENT > 5 mL", "c1ccncc1", "role = 'SOLVENT' AND volume_liters > 0.005"),
        ("carboxylic acid, as REAGENT", "C(=O)[OH]", "role = 'REAGENT'"),
        ("boronic acid, REACTANT > 1 mmol", "B(O)O", "role = 'REACTANT' AND moles > 0.001"),
    ]
    print(f"{'scenario':34s}{'screen':>10s}{'narrowed':>10s}{'ratio':>8s}"
          f"{'verify eager':>14s}{'verify narrow':>15s}")
    for label, smarts, predicate in scenarios:
        query = Chem.MolFromSmarts(smarts)
        qfp = Chem.PatternFingerprint(query, fpSize=BITS)
        qblob = np.packbits(
            np.frombuffer(qfp.ToBitString().encode(), "u1") - ord("0")).tobytes()
        params = {"q": qblob, "qpop": int(qfp.GetNumOnBits())}
        screen_sql = """bit_count(CAST(pattern_fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop"""

        eager = [row[0] for row in con.execute(
            f"SELECT smiles FROM structures WHERE {screen_sql}", params).fetchall()]
        narrowed = [row[0] for row in con.execute(f"""
            SELECT DISTINCT s.smiles FROM structures s
            WHERE {screen_sql} AND EXISTS (
              SELECT 1 FROM component_view v WHERE v.smiles = s.smiles AND {predicate})
        """, params).fetchall()]

        timings = []
        for candidates in (eager, narrowed):
            start = time.perf_counter()
            with mp.Pool(10, initializer=_init, initargs=(smarts,)) as pool:
                pool.map(_match, candidates, chunksize=2000)
            timings.append(time.perf_counter() - start)
        print(f"{label:34s}{len(eager):>10d}{len(narrowed):>10d}"
              f"{len(eager) / max(len(narrowed), 1):>7.0f}x"
              f"{timings[0]:>13.2f}s{timings[1]:>14.2f}s")
