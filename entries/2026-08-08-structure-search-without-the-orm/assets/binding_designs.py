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

"""Compare element-binding designs for a structure predicate, on the real corpus.

B  -- materialized flat component relation; binding is implicit in the row.
E  -- dense structure id on each component; the match set rides in as a bitmap
      parameter and the test happens inside the existing list lambda.
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
        np.frombuffer(fp.ToBitString().encode(), "u1") - ord("0")
    ).tobytes()


def _init(smarts):
    global _QUERY
    _QUERY = Chem.MolFromSmarts(smarts)


def _match(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None and mol.HasSubstructMatch(_QUERY)


def timeit(label, fn, repeat=3):
    best, result = float("inf"), None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        best = min(best, time.perf_counter() - start)
    print(f"  {label:44s} {best * 1000:7.0f} ms   -> {result}")
    return best


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{GLOB}', union_by_name=true)")

    # Dense structure ids over the distinct SMILES.
    con.execute("""
        CREATE TABLE structures AS
        SELECT smiles, (row_number() OVER (ORDER BY smiles) - 1)::UINTEGER AS structure_id
        FROM (SELECT DISTINCT unnest(list_transform(flatten(list_transform(
                map_values(inputs), x -> x.components)), e -> e.smiles)) AS smiles
              FROM r) WHERE smiles IS NOT NULL
    """)
    n_structures = con.execute("SELECT count(*) FROM structures").fetchone()[0]

    # B: flat component relation, structure_id attached.
    start = time.perf_counter()
    con.execute("""
        CREATE TABLE component_view AS
        SELECT f.reaction_id, s.structure_id, f.c.reaction_role AS role,
               f.c.amount.volume_liters AS volume_liters
        FROM (SELECT reaction_id, unnest(flatten(list_transform(map_values(inputs),
                     x -> x.components))) AS c FROM r) f
        JOIN structures s ON f.c.smiles = s.smiles
    """)
    print(f"B: component relation built in {time.perf_counter() - start:.1f}s")

    # E: the projection's nested shape, with structure_id inlined on each component.
    start = time.perf_counter()
    con.execute("""
        CREATE TABLE nested AS
        SELECT reaction_id, list(
                 {'structure_id': structure_id, 'role': role,
                  'volume_liters': volume_liters}) AS components
        FROM component_view GROUP BY reaction_id
    """)
    print(f"E: nested relation built in {time.perf_counter() - start:.1f}s")

    smiles_ids = con.execute("SELECT smiles, structure_id FROM structures").fetchall()
    with mp.Pool(10) as pool:
        featurized = [r for r in pool.map(_featurize, [s for s, _ in smiles_ids],
                                          chunksize=500) if r]
    con.register("structures_fp", pa.table({
        "smiles": pa.array([r[0] for r in featurized]),
        "pattern_fp": pa.array([r[1] for r in featurized], type=pa.binary()),
    }))

    for label, smarts, role in [("pyridine + SOLVENT", "c1ccncc1", "SOLVENT"),
                                ("boronic acid + REACTANT", "B(O)O", "REACTANT")]:
        print(f"\n=== {label} ===")
        query = Chem.MolFromSmarts(smarts)
        qfp = Chem.PatternFingerprint(query, fpSize=BITS)
        qblob = np.packbits(
            np.frombuffer(qfp.ToBitString().encode(), "u1") - ord("0")).tobytes()

        start = time.perf_counter()
        survivors = [row[0] for row in con.execute(
            """SELECT smiles FROM structures_fp
               WHERE bit_count(CAST(pattern_fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop""",
            {"q": qblob, "qpop": int(qfp.GetNumOnBits())}).fetchall()]
        screen = time.perf_counter() - start
        start = time.perf_counter()
        with mp.Pool(10, initializer=_init, initargs=(smarts,)) as pool:
            keep = pool.map(_match, survivors, chunksize=2000)
        matched = [s for s, k in zip(survivors, keep) if k]
        verify = time.perf_counter() - start
        print(f"  screen {screen * 1000:.0f} ms -> {len(survivors)} survivors; "
              f"verify {verify:.2f}s -> {len(matched)} structures")

        con.execute("DROP TABLE IF EXISTS matches")
        con.register("m_arrow", pa.table({"smiles": pa.array(matched)}))
        con.execute("""CREATE TABLE matches AS
                       SELECT s.structure_id FROM m_arrow a JOIN structures s
                       ON a.smiles = s.smiles""")

        # The match set as a bitmap over dense structure ids.
        start = time.perf_counter()
        bits = np.zeros(n_structures, dtype=np.uint8)
        bits[[r[0] for r in con.execute("SELECT structure_id FROM matches").fetchall()]] = 1
        bitmap = "".join(map(str, bits.tolist()))
        print(f"  bitmap: {len(bitmap) / 1024:.0f} KB built in "
              f"{(time.perf_counter() - start) * 1000:.0f} ms")

        timeit("B  semi-join on flat relation", lambda: con.execute("""
            SELECT count(DISTINCT reaction_id) FROM component_view v
            SEMI JOIN matches m ON v.structure_id = m.structure_id
            WHERE v.role = ?""", [role]).fetchone()[0])
        timeit("E  get_bit inside the list lambda", lambda: con.execute(f"""
            SELECT count(*) FROM nested
            WHERE len(list_filter(components, e ->
                  get_bit(CAST($m AS BITSTRING), e.structure_id::INTEGER) = 1
                  AND e.role = '{role}')) > 0""",
            {"m": bitmap}).fetchone()[0])
