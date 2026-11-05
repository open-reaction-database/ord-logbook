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

"""Makes every property required, expressing optionality as an explicit null instead.

Constrained decoding compiles a schema into a state machine, and an optional property
doubles it: the machine has to accept the object with and without that key. Requiring
every key and letting the value be null costs one token per absent field and leaves the
machine linear in the number of properties.
"""

import copy

# Keywords a decoder rejects or ignores. Dropping them costs nothing: the response is
# validated by the pydantic models afterwards, which enforce all of them anyway.
_UNSUPPORTED = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "maxItems",
        "uniqueItems",
        "default",
    }
)


def require_all(node, strip_descriptions: bool = False):
    """Returns node with every property required and nullable where it was optional."""
    if isinstance(node, list):
        return [require_all(item, strip_descriptions) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if strip_descriptions and key in ("description", "title", "examples"):
            continue
        # A decoder takes anyOf but not oneOf, and the discriminator that rides with it
        # is pydantic's business rather than the model's: validation still happens here.
        if key == "discriminator" or key in _UNSUPPORTED:
            continue
        out["anyOf" if key == "oneOf" else key] = require_all(value, strip_descriptions)
    properties = out.get("properties")
    if isinstance(properties, dict) and properties:
        required = set(out.get("required", []))
        for name, subschema in properties.items():
            if name in required:
                continue
            branches = subschema.get("anyOf") if isinstance(subschema, dict) else None
            if branches and any(b.get("type") == "null" for b in branches):
                continue
            properties[name] = {"anyOf": [subschema, {"type": "null"}]}
        out["required"] = sorted(properties)
        out["additionalProperties"] = False
    return out


def count_optional(node, seen=None) -> int:
    """Returns how many properties a schema leaves optional."""
    total = 0
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            total += len(set(properties) - set(node.get("required", [])))
        for value in node.values():
            total += count_optional(value)
    elif isinstance(node, list):
        for item in node:
            total += count_optional(item)
    return total


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from stratify import stratify

    from ord_schema.search import query

    base = query.Query.model_json_schema()
    print(f"{'depth':>6} {'optional before':>16} {'after':>6} {'~tokens':>9}")
    for depth in range(0, 5):
        built = stratify(copy.deepcopy(base), depth)
        before = count_optional(built)
        required = require_all(built, strip_descriptions=True)
        text = json.dumps(required)
        print(f"{depth:>6} {before:>16} {count_optional(required):>6} {len(text)//4:>9,}")
