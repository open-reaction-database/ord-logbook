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

"""Can a flattened predicate -- one object per level, path as an enum -- fit the budget?

The union of eight predicate variants is what multiplies the state machine, so this
collapses them into one object whose `op` says which shape it is. Paths become an enum,
which is the only way the decoder can stop a model inventing `identifiers[*]`.
"""

import json
import sys

import anthropic
import pyarrow as pa

from ord_schema.artifacts import projection

client = anthropic.Anthropic()


def leaf_paths(schema: pa.Schema) -> list[str]:
    """Returns every scalar column path in the projection, dotted."""
    found: list[str] = []

    def walk(field: pa.Field, prefix: str) -> None:
        path = f"{prefix}.{field.name}" if prefix else field.name
        dtype = field.type
        while pa.types.is_list(dtype) or pa.types.is_map(dtype):
            dtype = dtype.item_type if pa.types.is_map(dtype) else dtype.value_type
        if pa.types.is_struct(dtype):
            for child in dtype:
                walk(child, path)
        else:
            found.append(path)

    for field in schema:
        walk(field, "")
    return found


PATHS = leaf_paths(projection.SCHEMA)
print(f"projection leaves: {len(PATHS)}")


def predicate(level: int, paths: list[str]) -> dict:
    """Returns a flat predicate object whose clauses are one level shallower."""
    node: dict = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "op": {
                "type": "string",
                "enum": [
                    "and", "or", "not", "exists", "forall",
                    "eq", "ne", "lt", "le", "gt", "ge",
                    "contains", "starts_with", "ends_with",
                    "is_null", "not_null", "substructure", "similarity",
                ],
            },
            "path": {"anyOf": [{"type": "string", "enum": paths}, {"type": "null"}]},
            "literal": {"anyOf": [{"type": "string"}, {"type": "number"},
                                  {"type": "boolean"}, {"type": "null"}]},
            "compound": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "smarts": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["op", "path", "literal", "compound", "smarts"],
    }
    if level > 0:
        node["properties"]["clauses"] = {
            "anyOf": [{"type": "array", "items": predicate(level - 1, paths)},
                      {"type": "null"}]
        }
        node["required"].append("clauses")
    return node


for count in (0, 40, 120, len(PATHS)):
    paths = PATHS[:count] if count else ["<free string>"]
    for depth in (2, 3, 4):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"where": predicate(depth, paths)},
            "required": ["where"],
        }
        if not count:  # free-form path, for comparison with the enum forms
            schema = json.loads(json.dumps(schema).replace(
                '{"type": "string", "enum": ["<free string>"]}', '{"type": "string"}'))
        size = f"{len(json.dumps(schema)) // 4:,} ~tok"
        label = f"paths={count or 'free':>4} depth={depth}"
        try:
            client.messages.create(
                model="claude-haiku-4-5", max_tokens=256,
                messages=[{"role": "user", "content": "reactions above 350 K"}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIStatusError as error:
            message = json.loads(error.response.text)["error"]["message"]
            print(f"  {label}  {size:>12}  REFUSED: {message[:52]}")
        else:
            print(f"  {label}  {size:>12}  ACCEPTED")
