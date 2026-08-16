"""A flat component-fact table: one row per identifier, keyed back to the reaction.

Mirrors the ORM's derived.compound_smiles / derived.product_compound_smiles shape --
role lives in a column rather than in the table name, and component_index preserves
which component a fact belongs to so conjunctive predicates still work.
"""
import glob, json, os, time
import pyarrow as pa, pyarrow.parquet as pq
from ord_schema import message_helpers, parquet as ord_parquet
from ord_schema.logging import silence_rdkit_logs
from ord_schema.proto import reaction_pb2

silence_rdkit_logs()
CID = reaction_pb2.CompoundIdentifier
STRUCTURAL = {CID.SMILES, CID.CXSMILES, CID.INCHI, CID.MOLBLOCK}
name_of = CID.CompoundIdentifierType.Name

SCHEMA = pa.schema([
    pa.field("reaction_id", pa.string(), nullable=False),
    pa.field("role", pa.string(), nullable=False),
    pa.field("component_index", pa.int32(), nullable=False),
    pa.field("smiles", pa.string()),
    pa.field("identifier_type", pa.string()),
    pa.field("identifier_value", pa.string()),
])
OUT = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/facts.parquet"

def rows_for(reaction):
    rid = reaction.reaction_id
    pool = []
    for key in sorted(reaction.inputs):
        for c in reaction.inputs[key].components:
            pool.append(("INPUT", c))
    for outcome in reaction.outcomes:
        for p in outcome.products:
            pool.append(("OUTPUT", p))
    for index, (role, compound) in enumerate(pool):
        try:
            smiles = message_helpers.smiles_from_compound(compound) or None
        except Exception:
            smiles = None
        emitted = False
        for identifier in compound.identifiers:
            if identifier.type in STRUCTURAL or not identifier.value:
                continue
            emitted = True
            yield rid, role, index, smiles, name_of(identifier.type), identifier.value
        if not emitted:
            yield rid, role, index, smiles, None, None

t0 = time.time()
writer = pq.ParquetWriter(OUT, SCHEMA, compression="zstd")
batch, total = [], 0
for path in sorted(glob.glob("/Users/skearnes/ord/ord-data/data/*/*.parquet")):
    for item in ord_parquet.iter_reactions(path):
        reaction = item[1] if isinstance(item, tuple) else item
        batch.extend(rows_for(reaction))
        if len(batch) >= 500000:
            cols = list(zip(*batch))
            writer.write_table(pa.Table.from_arrays([pa.array(c) for c in cols], schema=SCHEMA))
            total += len(batch); batch = []
if batch:
    cols = list(zip(*batch))
    writer.write_table(pa.Table.from_arrays([pa.array(c) for c in cols], schema=SCHEMA))
    total += len(batch)
writer.close()
print(json.dumps({"fact_rows": total, "mb": round(os.path.getsize(OUT)/1e6, 1),
                  "minutes": round((time.time()-t0)/60, 1)}, indent=2))
