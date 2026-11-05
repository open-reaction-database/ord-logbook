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

"""Turns the recursive grammar into an acyclic one by stratifying it into levels.

The API refuses a schema whose definitions reference each other in a cycle, which is
what a predicate tree is. Stratifying keeps every definition but numbers it: a level-k
predicate's clauses are level-(k-1) predicates, and level 0 holds only the leaves. The
refs stay refs -- nothing is inlined, so size grows by a level rather than by a power --
and the result validates into the same recursive pydantic models.
"""

import copy
import json


def _referenced(node, found):
    """Collects the definition names ``node`` references."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref:
            found.add(ref.split("/")[-1])
        for value in node.values():
            _referenced(value, found)
    elif isinstance(node, list):
        for item in node:
            _referenced(item, found)
    return found


def _retarget(node, level, levelled):
    """Returns node with refs pointing at the next level down."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if ref:
            name = ref.split("/")[-1]
            if name not in levelled:
                return {"$ref": f"#/$defs/{name}"}
            if level <= 0:
                return None
            return {"$ref": f"#/$defs/{name}_L{level - 1}"}
        out = {}
        for key, value in node.items():
            result = _retarget(value, level, levelled)
            if result is None:
                if key in ("anyOf", "items", "properties"):
                    return None
                continue
            if isinstance(result, list) and not result:
                return None
            out[key] = result
        if "anyOf" in out and not out["anyOf"]:
            return None
        return out
    if isinstance(node, list):
        kept = [_retarget(item, level, levelled) for item in node]
        return [item for item in kept if item is not None]
    return node


def stratify(schema: dict, depth: int) -> dict:
    """Returns an acyclic schema whose predicates nest at most ``depth`` levels.

    Args:
        schema: A JSON Schema with a recursive ``$defs`` section.
        depth: How many levels of nesting to allow; level 0 holds only leaves.

    Returns:
        A schema with no reference cycle, its definitions suffixed by level.
    """
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})
    # A definition that reaches another definition is one a level has to renumber;
    # leaves reference nothing, so one copy of each serves every level.
    levelled = {name for name, node in defs.items() if _referenced(node, set())}
    out: dict = {}
    for name, node in defs.items():
        if name not in levelled:
            out[name] = node
            continue
        for level in range(depth + 1):
            built = _retarget(copy.deepcopy(node), level, levelled)
            if built is not None:
                out[f"{name}_L{level}"] = built
    root = _retarget(schema, depth, levelled)
    root["$defs"] = out
    return root


if __name__ == "__main__":
    from ord_schema.search import query

    base = query.Query.model_json_schema()
    print(f"{'depth':>6} {'chars':>9} {'~tokens':>8} {'defs':>6}")
    for depth in range(1, 7):
        built = stratify(base, depth)
        text = json.dumps(built)
        print(f"{depth:>6} {len(text):>9,} {len(text)//4:>8,} {len(built['$defs']):>6}")
