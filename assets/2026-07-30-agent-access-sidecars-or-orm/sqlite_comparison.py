"""Compare a SQLite data package against the Parquet sidecars on size and query time."""
import glob, json, os, sqlite3, time
import pyarrow.parquet as pq
import pyarrow.compute as pc

VIEWS = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/views_out2/*.parquet"
DB = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/ord.sqlite"
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(DB + suffix):
        os.remove(DB + suffix)

con = sqlite3.connect(DB)
con.executescript("""
PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
CREATE TABLE reaction (
  reaction_id TEXT PRIMARY KEY, reaction_smiles TEXT, yield_percent REAL,
  conversion_percent REAL, temperature_kelvin REAL, pressure_kilopascals REAL,
  reaction_time_seconds REAL, doi TEXT, patent TEXT);
CREATE TABLE component (
  reaction_id TEXT NOT NULL, role TEXT NOT NULL, smiles TEXT NOT NULL);
""")

t0 = time.time()
files = sorted(glob.glob(VIEWS))
for f in files:
    t = pq.read_table(f)
    cols = {n: t[n].to_pylist() for n in t.schema.names}
    con.executemany("INSERT INTO reaction VALUES (?,?,?,?,?,?,?,?,?)", zip(
        cols["reaction_id"], cols["reaction_smiles"], cols["yield_percent"],
        cols["conversion_percent"], cols["temperature_kelvin"],
        cols["pressure_kilopascals"], cols["reaction_time_seconds"],
        cols["doi"], cols["patent"]))
    rows = []
    for rid, ins, outs in zip(cols["reaction_id"], cols["input_smiles"], cols["output_smiles"]):
        for s in ins or ():
            rows.append((rid, "INPUT", s))
        for s in outs or ():
            rows.append((rid, "OUTPUT", s))
    con.executemany("INSERT INTO component VALUES (?,?,?)", rows)
    con.commit()
load_s = time.time() - t0
size_noidx = os.path.getsize(DB)

t0 = time.time()
con.executescript("""
CREATE INDEX component_smiles_index ON component (smiles);
CREATE INDEX component_reaction_index ON component (reaction_id);
CREATE INDEX reaction_yield_index ON reaction (yield_percent);
""")
con.commit()
index_s = time.time() - t0
con.close()
size_idx = os.path.getsize(DB)

parquet_bytes = sum(os.path.getsize(f) for f in files)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
def timed(sql):
    t0 = time.time(); r = con.execute(sql).fetchall(); return round(time.time() - t0, 3), r
q = {}
q["count"] = timed("SELECT count(*) FROM reaction")[0]
q["top_inputs"] = timed("SELECT smiles, count(*) c FROM component WHERE role='INPUT' GROUP BY smiles ORDER BY c DESC LIMIT 5")[0]
q["filtered_agg"] = timed("SELECT count(*), avg(yield_percent) FROM reaction WHERE temperature_kelvin > 350 AND yield_percent > 70")[0]
q["exact_component"] = timed("SELECT count(DISTINCT reaction_id) FROM component WHERE smiles = 'c1ccccc1'")[0]
q["point_lookup"] = timed("SELECT * FROM reaction WHERE reaction_id = 'ord-50b993b6ebfb4b48b92fb0b8d87e3751'")[0]
con.close()

print(json.dumps({
    "parquet_mb": round(parquet_bytes / 1e6, 1),
    "sqlite_mb_no_indexes": round(size_noidx / 1e6, 1),
    "sqlite_mb_with_indexes": round(size_idx / 1e6, 1),
    "sqlite_load_seconds": round(load_s, 1),
    "sqlite_index_seconds": round(index_s, 1),
    "sqlite_query_seconds": q,
}, indent=2))
