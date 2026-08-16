"""How often does C's reaction-granularity intersection differ from B's element binding?"""

import multiprocessing as mp
import time

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
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
    packed = np.packbits(np.frombuffer(fp.ToBitString().encode(), "u1") - ord("0"))
    return smiles, packed.tobytes()


def _init(smarts):
    global _QUERY
    _QUERY = Chem.MolFromSmarts(smarts)


def _match(smiles):
    mol = Chem.MolFromSmiles(smiles)
    return mol is not None and mol.HasSubstructMatch(_QUERY)


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW r AS SELECT * FROM read_parquet('{GLOB}', union_by_name=true)"
    )
    # Flatten once: this is the component view (B), materializing the UNNEST.
    start = time.perf_counter()
    con.execute("""
        CREATE TABLE components AS
        SELECT reaction_id, unnest(flatten(list_transform(map_values(inputs),
               x -> x.components))) AS c
        FROM r
    """)
    con.execute("""
        CREATE TABLE component_view AS
        SELECT reaction_id, c.smiles AS smiles, c.reaction_role AS role,
               c.amount.volume_liters AS volume_liters
        FROM components WHERE c.smiles IS NOT NULL
    """)
    n_components = con.execute("SELECT count(*) FROM component_view").fetchone()[0]
    print(f"component view: {n_components} rows in {time.perf_counter() - start:.1f}s")

    smiles = [
        row[0]
        for row in con.execute("SELECT DISTINCT smiles FROM component_view").fetchall()
    ]
    start = time.perf_counter()
    with mp.Pool(10) as pool:
        rows = [r for r in pool.map(_featurize, smiles, chunksize=500) if r]
    print(f"featurized {len(rows)} distinct in {time.perf_counter() - start:.1f}s")
    con.register(
        "structures",
        pa.table(
            {
                "smiles": pa.array([r[0] for r in rows]),
                "pattern_fp": pa.array([r[1] for r in rows], type=pa.binary()),
            }
        ),
    )

    for label, smarts, role in [
        ("pyridine + SOLVENT", "c1ccncc1", "SOLVENT"),
        ("boronic acid + REACTANT", "B(O)O", "REACTANT"),
        ("carboxylic acid + SOLVENT", "C(=O)[OH]", "SOLVENT"),
    ]:
        query = Chem.MolFromSmarts(smarts)
        qfp = Chem.PatternFingerprint(query, fpSize=BITS)
        qblob = np.packbits(
            np.frombuffer(qfp.ToBitString().encode(), "u1") - ord("0")
        ).tobytes()
        survivors = [
            row[0]
            for row in con.execute(
                """SELECT smiles FROM structures
                   WHERE bit_count(CAST(pattern_fp AS BITSTRING) & CAST($q AS BITSTRING)) = $qpop""",
                {"q": qblob, "qpop": int(qfp.GetNumOnBits())},
            ).fetchall()
        ]
        with mp.Pool(10, initializer=_init, initargs=(smarts,)) as pool:
            keep = pool.map(_match, survivors, chunksize=2000)
        matched = [s for s, k in zip(survivors, keep) if k]
        con.execute("DROP TABLE IF EXISTS matches")
        con.register("matched_arrow", pa.table({"smiles": pa.array(matched)}))
        con.execute("CREATE TABLE matches AS SELECT * FROM matched_arrow")

        # B: one component that is both.
        bound = con.execute(f"""
            SELECT count(DISTINCT reaction_id) FROM component_view v
            SEMI JOIN matches m ON v.smiles = m.smiles
            WHERE v.role = '{role}'
        """).fetchone()[0]
        # C: reactions matching the structure, intersected with reactions having the role.
        unbound = con.execute(f"""
            SELECT count(*) FROM (
              SELECT DISTINCT reaction_id FROM component_view v
              SEMI JOIN matches m ON v.smiles = m.smiles
              INTERSECT
              SELECT DISTINCT reaction_id FROM component_view WHERE role = '{role}')
        """).fetchone()[0]
        extra = unbound - bound
        print(
            f"{label:28s} {len(matched):7d} structures | B(bound) {bound:8d} | "
            f"C(intersect) {unbound:8d} | C over-returns {extra:8d} "
            f"({100 * extra / max(unbound, 1):.1f}% wrong)"
        )
