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

"""Normalized total EAV over the whole corpus.

Same normalizations as the nested projection -- united messages become one canonical
float leaf, structural identifiers collapse to one `smiles` leaf -- but emitted as
(reaction_id, path, entity_key, value) rows instead of nested columns.
"""
import glob, json, os, time
import pyarrow as pa, pyarrow.parquet as pq
from google.protobuf.descriptor import FieldDescriptor
from ord_schema import message_helpers, parquet as ord_parquet, units
from ord_schema.logging import silence_rdkit_logs
from ord_schema.proto import reaction_pb2

silence_rdkit_logs()
_RESOLVER = units.UnitResolver()
CANONICAL = {
    "Temperature": ("K", "kelvin"), "Pressure": ("kPa", "kilopascals"),
    "Time": ("s", "seconds"), "Mass": ("g", "grams"), "Moles": ("mol", "moles"),
    "Volume": ("L", "liters"), "Concentration": ("M", "molar"),
    "Current": ("A", "amperes"), "Voltage": ("V", "volts"),
    "Length": ("cm", "centimeters"), "FlowRate": ("mL/min", "milliliters_per_minute"),
}
CID, RID = reaction_pb2.CompoundIdentifier, reaction_pb2.ReactionIdentifier
STRUCT_C = {CID.SMILES, CID.CXSMILES, CID.INCHI, CID.MOLBLOCK}
STRUCT_R = {RID.REACTION_SMILES, RID.REACTION_CXSMILES}

SCHEMA = pa.schema([
    pa.field("reaction_id", pa.string(), nullable=False),
    pa.field("path", pa.string(), nullable=False),
    pa.field("entity_key", pa.string(), nullable=False),
    pa.field("value_text", pa.string()),
    pa.field("value_double", pa.float64()),
    pa.field("value_bool", pa.bool_()),
])

def walk(message, path, key, out):
    desc = message.DESCRIPTOR
    if desc.name in ("Compound", "ProductCompound"):
        try:
            s = message_helpers.smiles_from_compound(message) or None
        except Exception:
            s = None
        if s:
            out.append((f"{path}.smiles", f"{key}.smiles", s, None, None))
    elif desc.name == "Reaction":
        try:
            s = message_helpers.get_reaction_smiles(message, generate_if_missing=True) or None
        except Exception:
            s = None
        if s:
            out.append((f"{path}.smiles", f"{key}.smiles", s, None, None))
    for field in desc.fields:
        name = field.name
        mt = field.message_type
        if mt is not None and mt.name in CANONICAL:
            target, suffix = CANONICAL[mt.name]
            sub = getattr(message, name)
            try:
                if sub.HasField("value") and sub.units:
                    out.append((f"{path}.{name}_{suffix}", f"{key}.{name}_{suffix}",
                                None, _RESOLVER.convert(sub, target).value, None))
            except Exception:
                pass
            continue
        if mt is not None and mt.GetOptions().map_entry:
            vfield = mt.fields_by_name["value"]
            for k, v in getattr(message, name).items():
                if vfield.message_type is not None:
                    walk(v, f"{path}.{name}", f"{key}.{name}[{k}]", out)
                else:
                    out.append((f"{path}.{name}", f"{key}.{name}[{k}]", str(v), None, None))
            continue
        if field.label == FieldDescriptor.LABEL_REPEATED:
            values = list(getattr(message, name))
            if name == "identifiers" and desc.name in ("Compound", "ProductCompound"):
                values = [v for v in values if v.type not in STRUCT_C]
            elif name == "identifiers" and desc.name == "Reaction":
                values = [v for v in values if v.type not in STRUCT_R]
            for i, v in enumerate(values):
                if mt is not None:
                    walk(v, f"{path}.{name}", f"{key}.{name}[{i}]", out)
                elif field.type == FieldDescriptor.TYPE_ENUM:
                    out.append((f"{path}.{name}", f"{key}.{name}[{i}]",
                                field.enum_type.values_by_number[v].name, None, None))
                else:
                    out.append((f"{path}.{name}", f"{key}.{name}[{i}]", str(v), None, None))
            continue
        if mt is not None:
            if message.HasField(name):
                walk(getattr(message, name), f"{path}.{name}", f"{key}.{name}", out)
            continue
        try:
            present = message.HasField(name)
        except ValueError:
            present = bool(getattr(message, name))
        if not present:
            continue
        value = getattr(message, name)
        p, k = f"{path}.{name}", f"{key}.{name}"
        if field.type == FieldDescriptor.TYPE_ENUM:
            out.append((p, k, field.enum_type.values_by_number[value].name, None, None))
        elif field.type == FieldDescriptor.TYPE_BOOL:
            out.append((p, k, None, None, value))
        elif field.type in (FieldDescriptor.TYPE_STRING, FieldDescriptor.TYPE_BYTES):
            out.append((p, k, value if isinstance(value, str) else value.decode("utf8", "replace"), None, None))
        else:
            out.append((p, k, None, float(value), None))

OUT = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/norm_eav.parquet"
writer = pq.ParquetWriter(OUT, SCHEMA, compression="zstd")
buf, total, reactions, src = [], 0, 0, 0
t0 = time.time()
for path in sorted(glob.glob("/Users/skearnes/ord/ord-data/data/*/*.parquet")):
    src += os.path.getsize(path)
    for item in ord_parquet.iter_reactions(path):
        reaction = item[1] if isinstance(item, tuple) else item
        reactions += 1
        leaves = []
        walk(reaction, "reaction", "reaction", leaves)
        rid = reaction.reaction_id
        buf.extend((rid, p, k, t, d, b) for p, k, t, d, b in leaves)
        if len(buf) >= 400000:
            writer.write_table(pa.Table.from_arrays([pa.array(c) for c in zip(*buf)], schema=SCHEMA))
            total += len(buf); buf = []
    print(f"{os.path.basename(path)[:28]} reactions={reactions} facts={total}", flush=True)
if buf:
    writer.write_table(pa.Table.from_arrays([pa.array(c) for c in zip(*buf)], schema=SCHEMA))
    total += len(buf)
writer.close()
size = os.path.getsize(OUT)
print(json.dumps({"reactions": reactions, "fact_rows": total,
                  "facts_per_reaction": round(total/reactions, 1),
                  "mb": round(size/1e6, 1), "source_mb": round(src/1e6, 1),
                  "ratio_vs_source": round(size/src, 3),
                  "bytes_per_reaction": round(size/reactions, 1),
                  "minutes": round((time.time()-t0)/60, 1)}, indent=2))
