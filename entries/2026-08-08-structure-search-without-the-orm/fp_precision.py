"""Screen precision versus fingerprint width, and what it costs in verification."""

import multiprocessing as mp
import time

import duckdb
import numpy as np
import pyarrow as pa
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")
GLOB = "/Users/skearnes/ord/projections/*/*.parquet"
SIZES = [1024, 2048, 4096, 8192, 16384]
_SIZE = None
_QUERY = None


def _init_fp(size):
    global _SIZE
    _SIZE = size


def _featurize(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    fp = Chem.PatternFingerprint(mol, fpSize=_SIZE)
    return np.packbits(
        np.frombuffer(fp.ToBitString().encode(), "u1") - ord("0")
    ).tobytes()


def _init_match(smarts):
    global _QUERY
    _QUERY = Chem.MolFromSmarts(smarts)


def _match(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None and mol.HasSubstructMatch(_QUERY)


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{GLOB}', union_by_name=true)")
    smiles = [row[0] for row in con.execute("""
        SELECT DISTINCT unnest(list_transform(flatten(list_transform(
               map_values(inputs), x -> x.components)), e -> e.smiles)) AS s
        FROM r""").fetchall() if row[0] is not None]
    print(f"{len(smiles)} distinct structures\n")

    queries = [("pyridine", "c1ccncc1"), ("boronic acid", "B(O)O"),
               ("carboxylic acid", "C(=O)[OH]"), ("sulfonamide", "S(=O)(=O)N")]
    truth = {}
    for name, smarts in queries:
        with mp.Pool(10, initializer=_init_match, initargs=(smarts,)) as pool:
            truth[name] = sum(pool.map(_match, smiles, chunksize=2000))
        print(f"  ground truth {name:16s} {truth[name]:7d} true hits")

    print(f"\n{'query':17s}" + "".join(f"{s:>18d}" for s in SIZES))
    rows = {name: [] for name, _ in queries}
    build_times = {}
    for size in SIZES:
        start = time.perf_counter()
        with mp.Pool(10, initializer=_init_fp, initargs=(size,)) as pool:
            fps = pool.map(_featurize, smiles, chunksize=500)
        build_times[size] = time.perf_counter() - start
        keep = [(s, f) for s, f in zip(smiles, fps) if f is not None]
        con.execute("DROP TABLE IF EXISTS fp")
        con.register("fp_arrow", pa.table({
            "smiles": pa.array([k[0] for k in keep]),
            "pattern_fp": pa.array([k[1] for k in keep], type=pa.binary())}))
        con.execute("CREATE TABLE fp AS SELECT * FROM fp_arrow")
        for name, smarts in queries:
            qfp = Chem.PatternFingerprint(Chem.MolFromSmarts(smarts), fpSize=size)
            qblob = np.packbits(
                np.frombuffer(qfp.ToBitString().encode(), "u1") - ord("0")).tobytes()
            survivors = con.execute(
                """SELECT count(*) FROM fp WHERE
                   bit_count(CAST(pattern_fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop""",
                {"q": qblob, "qpop": int(qfp.GetNumOnBits())}).fetchone()[0]
            rows[name].append((survivors, 100 * truth[name] / max(survivors, 1)))
    for name, _ in queries:
        cells = "".join(f"{s:>10d} {p:5.0f}%" for s, p in rows[name])
        print(f"{name:17s}{cells}")
    print(f"\n{'build (s)':17s}" + "".join(f"{build_times[s]:>17.0f}s" for s in SIZES))
    print(f"{'bytes/structure':17s}" + "".join(f"{s // 8:>18d}" for s in SIZES))
