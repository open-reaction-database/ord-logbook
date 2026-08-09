"""Benchmark fingerprint screening over Parquet in DuckDB, at corpus scale."""

import time

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

N = 1_000_000
BITS = 2048
BYTES = BITS // 8
rng = np.random.default_rng(0)

# Morgan-like density: ~50 of 2048 bits set, varying per molecule.
counts = rng.integers(20, 120, size=N)
fps = np.zeros((N, BYTES), dtype=np.uint8)
for i in range(N):
    idx = rng.choice(BITS, size=counts[i], replace=False)
    packed = np.zeros(BITS, dtype=np.uint8)
    packed[idx] = 1
    fps[i] = np.packbits(packed)
popcount = np.unpackbits(fps, axis=1).sum(axis=1).astype(np.uint32)

table = pa.table(
    {
        "smiles": pa.array([f"C{i}" for i in range(N)]),
        "fp": pa.array([fps[i].tobytes() for i in range(N)], type=pa.binary()),
        "popcount": pa.array(popcount),
    }
)
# Sorted by popcount so row-group statistics bound the Tanimoto band.
table = table.sort_by("popcount")
pq.write_table(table, "fp_sorted.parquet", row_group_size=50_000, compression="zstd")
pq.write_table(
    table.sort_by("smiles"), "fp_unsorted.parquet", row_group_size=50_000, compression="zstd"
)
print("file size sorted   :", pq.ParquetFile("fp_sorted.parquet").metadata.serialized_size)
import os

for name in ("fp_sorted.parquet", "fp_unsorted.parquet"):
    print(f"{name}: {os.path.getsize(name) / 1e6:.0f} MB")

# A query fingerprint: small, like a pyridine pattern.
q = np.zeros(BITS, dtype=np.uint8)
q[rng.choice(BITS, size=25, replace=False)] = 1
qblob = np.packbits(q).tobytes()
qpop = int(q.sum())

con = duckdb.connect()


def timeit(label, sql, params=None, repeat=3):
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        result = con.execute(sql, params or {}).fetchall()
        best = min(best, time.perf_counter() - start)
    print(f"{label:52s} {best * 1000:8.0f} ms   {result[0]}")
    return best


print("\n--- substructure screen: bit containment over 1M ---")
timeit(
    "containment, BLOB->BITSTRING cast",
    """
    SELECT count(*) FROM read_parquet('fp_unsorted.parquet')
    WHERE bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop
    """,
    {"q": qblob, "qpop": qpop},
)

print("\n--- similarity: Tanimoto over 1M ---")
timeit(
    "tanimoto >= 0.7, full scan (unsorted)",
    """
    SELECT count(*) FROM read_parquet('fp_unsorted.parquet')
    WHERE bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))::DOUBLE
          / (popcount + $qpop - bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))) >= 0.7
    """,
    {"q": qblob, "qpop": qpop},
)

# Tanimoto bound: popcount(B) in [t*popcount(A), popcount(A)/t]
qpop_big = 60
q2 = np.zeros(BITS, dtype=np.uint8)
q2[rng.choice(BITS, size=qpop_big, replace=False)] = 1
q2blob = np.packbits(q2).tobytes()
lo, hi = int(0.7 * qpop_big), int(qpop_big / 0.7)
print(f"\n--- popcount band pruning: [{lo}, {hi}] of observed [20,120] ---")
timeit(
    "tanimoto >= 0.7 with band, SORTED parquet",
    f"""
    SELECT count(*) FROM read_parquet('fp_sorted.parquet')
    WHERE popcount BETWEEN {lo} AND {hi}
      AND bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))::DOUBLE
          / (popcount + $qpop - bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))) >= 0.7
    """,
    {"q": q2blob, "qpop": qpop_big},
)
timeit(
    "tanimoto >= 0.7 with band, UNSORTED parquet",
    f"""
    SELECT count(*) FROM read_parquet('fp_unsorted.parquet')
    WHERE popcount BETWEEN {lo} AND {hi}
      AND bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))::DOUBLE
          / (popcount + $qpop - bit_count(CAST(fp AS BITSTRING) & CAST($q AS BITSTRING))) >= 0.7
    """,
    {"q": q2blob, "qpop": qpop_big},
)
