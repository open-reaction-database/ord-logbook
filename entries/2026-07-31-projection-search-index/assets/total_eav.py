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

"""Total EAV: one row per populated scalar leaf, with the full positional path.

Columns: reaction_id, path (dotted, indices stripped), entity_key (path WITH indices,
so co-membership and position both survive), and typed value columns.
"""
import glob, json, os, sys, time
import pyarrow as pa, pyarrow.parquet as pq
from google.protobuf.descriptor import FieldDescriptor
from ord_schema import parquet as ord_parquet
from ord_schema.proto import reaction_pb2

SCHEMA = pa.schema([
    pa.field("reaction_id", pa.string(), nullable=False),
    pa.field("path", pa.string(), nullable=False),
    pa.field("entity_key", pa.string(), nullable=False),
    pa.field("value_text", pa.string()),
    pa.field("value_double", pa.float64()),
    pa.field("value_bool", pa.bool_()),
])

def walk(message, path, key, out):
    for field in message.DESCRIPTOR.fields:
        name = field.name
        if field.message_type is not None and field.message_type.GetOptions().map_entry:
            vfield = field.message_type.fields_by_name["value"]
            for k, v in getattr(message, name).items():
                if vfield.message_type is not None:
                    walk(v, f"{path}.{name}", f"{key}.{name}[{k}]", out)
                else:
                    out.append((f"{path}.{name}", f"{key}.{name}[{k}]", str(v), None, None))
            continue
        if field.label == FieldDescriptor.LABEL_REPEATED:
            for i, v in enumerate(getattr(message, name)):
                if field.message_type is not None:
                    walk(v, f"{path}.{name}", f"{key}.{name}[{i}]", out)
                elif field.type == FieldDescriptor.TYPE_ENUM:
                    out.append((f"{path}.{name}", f"{key}.{name}[{i}]",
                                field.enum_type.values_by_number[v].name, None, None))
                else:
                    out.append((f"{path}.{name}", f"{key}.{name}[{i}]", str(v), None, None))
            continue
        if field.message_type is not None:
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

path_in = sys.argv[1]; limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
dest = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/eav_" + os.path.basename(path_in)
writer = pq.ParquetWriter(dest, SCHEMA, compression="zstd")
rows, n, total, t0 = [], 0, 0, time.time()
for item in ord_parquet.iter_reactions(path_in):
    if limit and n >= limit: break
    reaction = item[1] if isinstance(item, tuple) else item
    n += 1
    leaves = []
    walk(reaction, "reaction", "reaction", leaves)
    rid = reaction.reaction_id
    rows.extend((rid, p, k, t, d, b) for p, k, t, d, b in leaves)
    if len(rows) >= 400000:
        writer.write_table(pa.Table.from_arrays([pa.array(c) for c in zip(*rows)], schema=SCHEMA))
        total += len(rows); rows = []
if rows:
    writer.write_table(pa.Table.from_arrays([pa.array(c) for c in zip(*rows)], schema=SCHEMA))
    total += len(rows)
writer.close()
print(json.dumps({"dataset": os.path.basename(path_in)[:28], "reactions": n, "fact_rows": total,
                  "facts_per_reaction": round(total/n, 1), "mb": round(os.path.getsize(dest)/1e6, 2),
                  "bytes_per_reaction": round(os.path.getsize(dest)/n, 1),
                  "seconds": round(time.time()-t0, 1)}, indent=2))
