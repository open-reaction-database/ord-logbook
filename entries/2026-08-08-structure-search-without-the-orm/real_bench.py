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

"""Screen + verify a real substructure query over real ORD structures."""

import multiprocessing as mp
import time

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from rdkit import Chem, RDLogger
from rdkit.Chem import rdFingerprintGenerator

RDLogger.DisableLog("rdApp.*")

N = 200_000
BITS = 2048


def featurize(smiles: str) -> tuple[str, bytes, bytes, int] | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    pattern = Chem.PatternFingerprint(mol, fpSize=BITS)
    morgan = rdFingerprintGenerator.GetMorganGenerator(
        radius=2, fpSize=BITS
    ).GetFingerprint(mol)
    p = np.packbits(np.frombuffer(pattern.ToBitString().encode(), "u1") - ord("0"))
    m = np.packbits(np.frombuffer(morgan.ToBitString().encode(), "u1") - ord("0"))
    return smiles, p.tobytes(), m.tobytes(), int(morgan.GetNumOnBits())


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(
        "CREATE VIEW r AS SELECT * FROM read_parquet"
        "('/Users/skearnes/ord/projections/*/*.parquet', union_by_name=true)"
    )
    start = time.perf_counter()
    smiles = [
        row[0]
        for row in con.execute(f"""
        SELECT DISTINCT s FROM (
          SELECT unnest(list_transform(flatten(list_transform(map_values(inputs),
                 x -> x.components)), e -> e.smiles)) AS s FROM r)
        WHERE s IS NOT NULL LIMIT {N}
    """).fetchall()
    ]
    print(f"pulled {len(smiles)} distinct SMILES in {time.perf_counter() - start:.1f}s")

    start = time.perf_counter()
    with mp.Pool(10) as pool:
        rows = [r for r in pool.map(featurize, smiles, chunksize=500) if r is not None]
    build = time.perf_counter() - start
    print(f"featurized {len(rows)} in {build:.1f}s  ({len(rows) / build:.0f}/s)")

    table = pa.table(
        {
            "smiles": pa.array([r[0] for r in rows]),
            "pattern_fp": pa.array([r[1] for r in rows], type=pa.binary()),
            "morgan_fp": pa.array([r[2] for r in rows], type=pa.binary()),
            "morgan_popcount": pa.array([r[3] for r in rows], type=pa.uint32()),
        }
    ).sort_by("morgan_popcount")
    pq.write_table(table, "structures.parquet", row_group_size=50_000, compression="zstd")
    import os

    print(f"structures.parquet: {os.path.getsize('structures.parquet') / 1e6:.0f} MB "
          f"for {len(rows)} structures")

    for name, smarts in [
        ("pyridine", "c1ccncc1"),
        ("benzene", "c1ccccc1"),
        ("carboxylic acid", "C(=O)[OH]"),
        ("boronic acid", "B(O)O"),
    ]:
        query = Chem.MolFromSmarts(smarts)
        qfp = Chem.PatternFingerprint(query, fpSize=BITS)
        qblob = np.packbits(
            np.frombuffer(qfp.ToBitString().encode(), "u1") - ord("0")
        ).tobytes()
        qpop = int(qfp.GetNumOnBits())

        start = time.perf_counter()
        survivors = [
            row[0]
            for row in con.execute(
                """
            SELECT smiles FROM read_parquet('structures.parquet')
            WHERE bit_count(CAST(pattern_fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop
            """,
                {"q": qblob, "qpop": qpop},
            ).fetchall()
        ]
        screen = time.perf_counter() - start

        start = time.perf_counter()
        hits = sum(
            1
            for s in survivors
            if (m := Chem.MolFromSmiles(s)) is not None and m.HasSubstructMatch(query)
        )
        verify = time.perf_counter() - start
        print(
            f"{name:16s} screen {screen * 1000:6.0f} ms -> {len(survivors):7d} survivors "
            f"({100 * len(survivors) / len(rows):5.1f}%)  verify {verify:6.2f}s -> {hits} hits "
            f"(screen precision {100 * hits / max(len(survivors), 1):.0f}%)"
        )
