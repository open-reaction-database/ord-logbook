"""Build a local name -> SMILES index from the PubChem bulk dumps.

Inputs are the two files under https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/ :
`CID-Synonym-filtered.gz` (cid, synonym) and `CID-SMILES.gz` (cid, isomeric SMILES).
Names are folded to lowercase and whitespace-trimmed, matching the case-insensitive
lookup PubChem's REST name endpoint performs.

A name can name several CIDs (salts, tautomers, stereoisomers, and depositor
disagreement all produce this). The index keeps the lowest CID, which is PubChem's
oldest record for the name and usually the parent form, and stores how many CIDs the
name matched so a caller can treat an ambiguous hit differently if it wants to.

Emits both storage forms so they can be compared: a ZSTD Parquet file for DuckDB and a
SQLite database with a covering index.

Usage: build_index.py SOURCE_DIR OUT_DIR
"""

import argparse
import pathlib
import sqlite3
import time

import duckdb

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source_dir", type=pathlib.Path)
parser.add_argument("out_dir", type=pathlib.Path)
parser.add_argument("--memory-limit", default="16GB")
args = parser.parse_args()
args.out_dir.mkdir(parents=True, exist_ok=True)

parquet_path = args.out_dir / "pubchem_names.parquet"
sqlite_path = args.out_dir / "pubchem_names.sqlite"
timings: dict[str, float] = {}


class Step:
    """Times a build step and records it under ``name``."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.start = time.monotonic()
        print(f"[{self.name}] ...", flush=True)
        return self

    def __exit__(self, *exc):
        timings[self.name] = time.monotonic() - self.start
        print(f"[{self.name}] {timings[self.name]:.1f}s", flush=True)


con = duckdb.connect(database=":memory:")
con.execute(f"SET memory_limit='{args.memory_limit}'")
con.execute(f"SET temp_directory='{args.out_dir / 'duckdb_tmp'}'")

# quote='' and escape='': synonyms contain bare double quotes (e.g. cis/trans locants
# written as 2"-...), which the CSV reader would otherwise treat as field quoting and
# swallow the rest of the line.
read_options = (
    "delim='\t', header=false, quote='', escape='', "
    "ignore_errors=true, parallel=false"
)

with Step("scan synonyms"):
    con.execute(
        f"""
        CREATE TABLE synonym AS
        SELECT lower(trim(name)) AS name, cid
        FROM read_csv('{args.source_dir / "CID-Synonym-filtered.gz"}',
                      columns={{'cid': 'UBIGINT', 'name': 'VARCHAR'}}, {read_options})
        WHERE name IS NOT NULL AND length(trim(name)) > 0
        """
    )
    synonym_rows = con.sql("SELECT count(*) FROM synonym").fetchone()[0]

with Step("collapse to one cid per name"):
    con.execute(
        """
        CREATE TABLE name_cid AS
        SELECT name, min(cid) AS cid, count(DISTINCT cid) AS n_cids
        FROM synonym GROUP BY name
        """
    )
    con.execute("DROP TABLE synonym")
    unique_names = con.sql("SELECT count(*) FROM name_cid").fetchone()[0]

with Step("scan smiles"):
    con.execute(
        f"""
        CREATE TABLE smiles AS
        SELECT cid, smiles
        FROM read_csv('{args.source_dir / "CID-SMILES.gz"}',
                      columns={{'cid': 'UBIGINT', 'smiles': 'VARCHAR'}}, {read_options})
        """
    )
    smiles_rows = con.sql("SELECT count(*) FROM smiles").fetchone()[0]

with Step("join and write parquet"):
    con.execute(
        f"""
        COPY (
            SELECT n.name, s.smiles, n.cid, n.n_cids
            FROM name_cid n JOIN smiles s USING (cid)
            ORDER BY n.name
        ) TO '{parquet_path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)
        """
    )
    indexed_names = con.sql(
        f"SELECT count(*) FROM read_parquet('{parquet_path}')"
    ).fetchone()[0]

with Step("write sqlite"):
    sqlite_path.unlink(missing_ok=True)
    sqlite_con = sqlite3.connect(sqlite_path)
    sqlite_con.executescript(
        "PRAGMA journal_mode=off; PRAGMA synchronous=off;"
        "CREATE TABLE name_smiles (name TEXT PRIMARY KEY, smiles TEXT NOT NULL,"
        " cid INTEGER NOT NULL, n_cids INTEGER NOT NULL) WITHOUT ROWID;"
    )
    batch_size = 1_000_000
    reader = con.execute(
        f"SELECT name, smiles, cid, n_cids FROM read_parquet('{parquet_path}')"
    )
    while batch := reader.fetchmany(batch_size):
        sqlite_con.executemany("INSERT INTO name_smiles VALUES (?, ?, ?, ?)", batch)
    sqlite_con.commit()
    sqlite_con.execute("VACUUM")
    sqlite_con.close()

print()
print(f"synonym rows read      {synonym_rows:>13,}")
print(f"unique normalized names{unique_names:>13,}")
print(f"cid-smiles rows read   {smiles_rows:>13,}")
print(f"names with a structure {indexed_names:>13,}")
print(f"parquet                {parquet_path.stat().st_size:>13,} bytes")
print(f"sqlite                 {sqlite_path.stat().st_size:>13,} bytes")
print(f"total build            {sum(timings.values()):>13.1f}s")
