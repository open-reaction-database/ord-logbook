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

"""How often does a forced tool call over the recursive grammar parse as written?

Runs a handful of questions through two models and scores three ways: as returned,
after coercing JSON-encoded strings back to objects, and whether the compiler accepts
the result. The gap between the first two is what a strict schema would have bought.
"""

import json

import anthropic

from ord_schema.search import query, schema

QUESTIONS = [
    "reactions using pyridine as the solvent",
    "reactions using pyridine as the solvent with a yield above 50%",
    "reactions run above 350 K",
    "reactions where every input component is a liquid",
    "average yield by reaction temperature, for reactions with a boronic acid",
]
SYSTEM = [
    {
        "type": "text",
        "text": (
            "You translate chemistry questions into ORD search queries. Emit the query "
            "by calling build_query. The corpus schema, as an indented type tree in "
            "DuckDB's types:\n\n" + schema.describe()
        ),
        "cache_control": {"type": "ephemeral"},
    }
]
TOOL = {
    "name": "build_query",
    "description": "Build an ORD search query from the user's question.",
    "input_schema": query.Query.model_json_schema(),
}


def coerce(value):
    """Returns the input with any JSON-encoded string values parsed back to objects."""
    if isinstance(value, str):
        try:
            return coerce(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value
    if isinstance(value, dict):
        return {key: coerce(item) for key, item in value.items()}
    if isinstance(value, list):
        return [coerce(item) for item in value]
    return value


client = anthropic.Anthropic()
for model in ("claude-opus-5", "claude-haiku-4-5"):
    print(f"\n=== {model}")
    tallies = {"as written": 0, "coerced": 0, "compiles": 0}
    cost = {"cache_write": 0, "cache_read": 0, "input": 0, "output": 0}
    for question in QUESTIONS:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": question}],
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "build_query"},
        )
        usage = response.usage
        cost["cache_write"] += usage.cache_creation_input_tokens or 0
        cost["cache_read"] += usage.cache_read_input_tokens or 0
        cost["input"] += usage.input_tokens
        cost["output"] += usage.output_tokens
        raw = next(b for b in response.content if b.type == "tool_use").input
        note = []
        try:
            query.Query.model_validate(raw)
        except Exception:  # noqa: BLE001 -- scoring, not handling.
            note.append("as-written FAILED")
        else:
            tallies["as written"] += 1
            note.append("as-written ok")
        try:
            parsed = query.Query.model_validate(coerce(raw))
        except Exception as error:  # noqa: BLE001
            note.append(f"coerced FAILED: {str(error)[:60]}")
        else:
            tallies["coerced"] += 1
            try:
                query.compile_query(parsed)
            except Exception as error:  # noqa: BLE001
                note.append(f"compile FAILED: {str(error)[:80]}")
            else:
                tallies["compiles"] += 1
                note.append("compiles")
        print(f"  {question[:52]:54} {' | '.join(note)}")
    print(f"  tallies (of {len(QUESTIONS)}): {tallies}")
    print(f"  tokens: {cost}")
