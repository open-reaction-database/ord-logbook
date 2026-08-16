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

"""Project the entire Reaction proto into nested Arrow, descriptor-driven.

No curation: every field of every reachable message becomes a column, repeated fields
become lists, maps become maps, enums become strings. Measures what "arbitrary queries
over the full model" costs as a Parquet artifact.
"""
import json, os, sys, time
import pyarrow as pa
import pyarrow.parquet as pq
from google.protobuf.descriptor import FieldDescriptor
from ord_schema import parquet as ord_parquet
from ord_schema.proto import reaction_pb2

_SCALARS = {
    FieldDescriptor.TYPE_DOUBLE: pa.float64(), FieldDescriptor.TYPE_FLOAT: pa.float32(),
    FieldDescriptor.TYPE_INT64: pa.int64(), FieldDescriptor.TYPE_UINT64: pa.uint64(),
    FieldDescriptor.TYPE_INT32: pa.int32(), FieldDescriptor.TYPE_UINT32: pa.uint32(),
    FieldDescriptor.TYPE_BOOL: pa.bool_(), FieldDescriptor.TYPE_STRING: pa.string(),
    FieldDescriptor.TYPE_BYTES: pa.binary(), FieldDescriptor.TYPE_ENUM: pa.string(),
}

def field_type(field):
    if field.message_type is not None and field.message_type.GetOptions().map_entry:
        k, v = field.message_type.fields_by_name["key"], field.message_type.fields_by_name["value"]
        return pa.map_(field_type(k), field_type(v))
    if field.message_type is not None:
        inner = pa.struct([pa.field(f.name, field_type(f)) for f in field.message_type.fields])
    else:
        inner = _SCALARS[field.type]
    if field.label == FieldDescriptor.LABEL_REPEATED:
        return pa.list_(inner)
    return inner

def to_py(message):
    out = {}
    for field in message.DESCRIPTOR.fields:
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            m = getattr(message, field.name)
            vfield = field.message_type.fields_by_name["value"]
            if vfield.message_type is not None:
                out[field.name] = [(k, to_py(v)) for k, v in m.items()] or None
            else:
                out[field.name] = list(m.items()) or None
            continue
        if field.label == FieldDescriptor.LABEL_REPEATED:
            values = getattr(message, field.name)
            if field.message_type is not None:
                out[field.name] = [to_py(v) for v in values] or None
            elif field.type == FieldDescriptor.TYPE_ENUM:
                out[field.name] = [field.enum_type.values_by_number[v].name for v in values] or None
            else:
                out[field.name] = list(values) or None
            continue
        if field.message_type is not None:
            out[field.name] = to_py(getattr(message, field.name)) if message.HasField(field.name) else None
            continue
        try:
            present = message.HasField(field.name)
        except ValueError:
            present = bool(getattr(message, field.name))
        if not present:
            out[field.name] = None
        elif field.type == FieldDescriptor.TYPE_ENUM:
            out[field.name] = field.enum_type.values_by_number[getattr(message, field.name)].name
        else:
            out[field.name] = getattr(message, field.name)
    return out

SCHEMA = pa.schema([pa.field(f.name, field_type(f)) for f in reaction_pb2.Reaction.DESCRIPTOR.fields])

def run(path, limit=None):
    rows, t0 = [], time.time()
    for n, item in enumerate(ord_parquet.iter_reactions(path)):
        if limit and n >= limit:
            break
        rows.append(to_py(item[1] if isinstance(item, tuple) else item))
    convert_s = time.time() - t0
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    out = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/full_%s" % os.path.basename(path)
    pq.write_table(table, out, compression="zstd")
    return {"dataset": os.path.basename(path)[:28], "rows": len(rows),
            "convert_seconds": round(convert_s, 1),
            "full_mb": round(os.path.getsize(out) / 1e6, 2),
            "bytes_per_row": round(os.path.getsize(out) / len(rows), 1),
            "top_level_columns": len(SCHEMA)}

if __name__ == "__main__":
    print("top-level columns:", len(SCHEMA))
    results = [run(p, limit=int(sys.argv[2]) if len(sys.argv) > 2 else None) for p in sys.argv[1:2]]
    print(json.dumps(results, indent=2))
