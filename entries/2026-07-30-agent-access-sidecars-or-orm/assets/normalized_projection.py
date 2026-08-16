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

"""Normalized total projection: units to canonical floats, structural identifiers to one SMILES.

Everything else is projected verbatim. Non-structural identifiers (NAME, CAS_NUMBER,
CUSTOM, ...) are kept as a list, because 1,088,493 compounds carry more than one NAME.
"""
import json, os, sys, time
import pyarrow as pa
import pyarrow.parquet as pq
from google.protobuf.descriptor import FieldDescriptor
from rdkit import Chem

import ord_schema
from ord_schema import message_helpers, parquet as ord_parquet, units
from ord_schema.logging import silence_rdkit_logs
from ord_schema.proto import reaction_pb2

silence_rdkit_logs()
_RESOLVER = units.UnitResolver()

# Canonical unit per united message type, and the suffix its column carries.
CANONICAL = {
    "Temperature": ("K", "kelvin"), "Pressure": ("kPa", "kilopascals"),
    "Time": ("s", "seconds"), "Mass": ("g", "grams"), "Moles": ("mol", "moles"),
    "Volume": ("L", "liters"), "Concentration": ("M", "molar"),
    "Current": ("A", "amperes"), "Voltage": ("V", "volts"),
    "Length": ("cm", "centimeters"), "FlowRate": ("mL/min", "milliliters_per_minute"),
}
CID = reaction_pb2.CompoundIdentifier
RID = reaction_pb2.ReactionIdentifier
STRUCTURAL_COMPOUND = {CID.SMILES, CID.CXSMILES, CID.INCHI, CID.MOLBLOCK}
STRUCTURAL_REACTION = {RID.REACTION_SMILES, RID.REACTION_CXSMILES}
IDENTIFIER_MESSAGES = {"CompoundIdentifier", "ReactionIdentifier"}

_SCALARS = {
    FieldDescriptor.TYPE_DOUBLE: pa.float64(), FieldDescriptor.TYPE_FLOAT: pa.float32(),
    FieldDescriptor.TYPE_INT64: pa.int64(), FieldDescriptor.TYPE_UINT64: pa.uint64(),
    FieldDescriptor.TYPE_INT32: pa.int32(), FieldDescriptor.TYPE_UINT32: pa.uint32(),
    FieldDescriptor.TYPE_BOOL: pa.bool_(), FieldDescriptor.TYPE_STRING: pa.string(),
    FieldDescriptor.TYPE_BYTES: pa.binary(), FieldDescriptor.TYPE_ENUM: pa.string(),
}

def field_name(field):
    if field.message_type is not None and field.message_type.name in CANONICAL:
        return f"{field.name}_{CANONICAL[field.message_type.name][1]}"
    return field.name

def struct_fields(desc):
    out = []
    if desc.name in ("Compound", "ProductCompound", "Reaction"):
        out.append(pa.field("smiles", pa.string()))
    for f in desc.fields:
        out.append(pa.field(field_name(f), field_type(f)))
    return out

def field_type(field):
    if field.message_type is not None and field.message_type.name in CANONICAL:
        return pa.float64()
    if field.message_type is not None and field.message_type.GetOptions().map_entry:
        k, v = field.message_type.fields_by_name["key"], field.message_type.fields_by_name["value"]
        return pa.map_(field_type(k), field_type(v))
    if field.message_type is not None:
        inner = pa.struct(struct_fields(field.message_type))
    else:
        inner = _SCALARS[field.type]
    if field.label == FieldDescriptor.LABEL_REPEATED:
        return pa.list_(inner)
    return inner

def canonical_smiles_for(message, structural):
    try:
        return message_helpers.smiles_from_compound(message) or None
    except Exception:
        pass
    for identifier in message.identifiers:
        if identifier.type in structural and identifier.value:
            return identifier.value
    return None

def to_py(message):
    desc = message.DESCRIPTOR
    out = {}
    if desc.name in ("Compound", "ProductCompound"):
        out["smiles"] = canonical_smiles_for(message, STRUCTURAL_COMPOUND)
    elif desc.name == "Reaction":
        try:
            out["smiles"] = message_helpers.get_reaction_smiles(message, generate_if_missing=True) or None
        except Exception:
            out["smiles"] = None
    for field in desc.fields:
        key = field_name(field)
        if field.message_type is not None and field.message_type.name in CANONICAL:
            target = CANONICAL[field.message_type.name][0]
            sub = getattr(message, field.name)
            try:
                out[key] = _RESOLVER.convert(sub, target).value if (sub.HasField("value") and sub.units) else None
            except Exception:
                out[key] = None
            continue
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            m = getattr(message, field.name)
            vfield = field.message_type.fields_by_name["value"]
            out[key] = ([(k, to_py(v)) for k, v in m.items()] if vfield.message_type is not None
                        else list(m.items())) or None
            continue
        if field.label == FieldDescriptor.LABEL_REPEATED:
            values = getattr(message, field.name)
            if field.name == "identifiers" and desc.name in ("Compound", "ProductCompound"):
                values = [v for v in values if v.type not in STRUCTURAL_COMPOUND]
            elif field.name == "identifiers" and desc.name == "Reaction":
                values = [v for v in values if v.type not in STRUCTURAL_REACTION]
            if field.message_type is not None:
                out[key] = [to_py(v) for v in values] or None
            elif field.type == FieldDescriptor.TYPE_ENUM:
                out[key] = [field.enum_type.values_by_number[v].name for v in values] or None
            else:
                out[key] = list(values) or None
            continue
        if field.message_type is not None:
            out[key] = to_py(getattr(message, field.name)) if message.HasField(field.name) else None
            continue
        try:
            present = message.HasField(field.name)
        except ValueError:
            present = bool(getattr(message, field.name))
        if not present:
            out[key] = None
        elif field.type == FieldDescriptor.TYPE_ENUM:
            out[key] = field.enum_type.values_by_number[getattr(message, field.name)].name
        else:
            out[key] = getattr(message, field.name)
    return out

SCHEMA = pa.schema(struct_fields(reaction_pb2.Reaction.DESCRIPTOR))

def leaf_count(t):
    if pa.types.is_struct(t): return sum(leaf_count(f.type) for f in t)
    if pa.types.is_list(t): return leaf_count(t.value_type)
    if pa.types.is_map(t): return leaf_count(t.item_type) + 1
    return 1

if __name__ == "__main__":
    print("leaf columns (normalized):", sum(leaf_count(f.type) for f in SCHEMA))
    path = sys.argv[1]; limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    rows, t0 = [], time.time()
    for n, item in enumerate(ord_parquet.iter_reactions(path)):
        if limit and n >= limit: break
        rows.append(to_py(item[1] if isinstance(item, tuple) else item))
    convert_s = time.time() - t0
    out = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/norm_" + os.path.basename(path)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out, compression="zstd")
    print(json.dumps({"dataset": os.path.basename(path)[:28], "rows": len(rows),
                      "convert_seconds": round(convert_s, 1),
                      "normalized_mb": round(os.path.getsize(out) / 1e6, 2),
                      "bytes_per_row": round(os.path.getsize(out) / len(rows), 1)}, indent=2))
