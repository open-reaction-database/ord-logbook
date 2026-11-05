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

"""Does one repair turn carry a cheap model to the accuracy of an expensive one?

The compiler's errors name the offending path and suggest a real one, so a failed
translation is handed straight back. Scores first-try and after-repair separately.
"""

import json
import sys

import anthropic

from ord_schema.search import query, schema

QUESTIONS = [
    "reactions using pyridine as the solvent",
    "reactions using pyridine as the solvent with a yield above 50%",
    "reactions run above 350 K",
    "reactions where every input component is a liquid",
    "average yield by reaction temperature, for reactions with a boronic acid",
    "reactions that make aspirin",
    "the ten highest-yielding Suzuki couplings",
    "reactions with no solvent at all",
    "how many reactions use palladium catalysts",
    "reactions stirred for more than an hour at above 100 C",
]
SYSTEM = [
    {
        "type": "text",
        "text": (
            "You translate chemistry questions into ORD search queries by calling "
            "build_query. The corpus schema, as an indented type tree in DuckDB's "
            "types:\n\n" + schema.describe()
        ),
        "cache_control": {"type": "ephemeral"},
    }
]
TOOL = {
    "name": "build_query",
    "description": "Build an ORD search query from the user's question.",
    "input_schema": query.Query.model_json_schema(),
}
MODEL = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-4-5"


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


def check(raw) -> str | None:
    """Returns the error a translation fails with, or None if it compiles."""
    try:
        query.compile_query(query.Query.model_validate(coerce(raw)))
    except Exception as error:  # noqa: BLE001 -- whatever it fails with is the message.
        return str(error)
    return None


client = anthropic.Anthropic()
first_try = repaired = 0
cost = {"cache_read": 0, "input": 0, "output": 0}
for question in QUESTIONS:
    messages: list = [{"role": "user", "content": question}]
    response = client.messages.create(
        model=MODEL, max_tokens=2048, system=SYSTEM, messages=messages,
        tools=[TOOL], tool_choice={"type": "tool", "name": "build_query"},
    )
    cost["cache_read"] += response.usage.cache_read_input_tokens or 0
    cost["input"] += response.usage.input_tokens
    cost["output"] += response.usage.output_tokens
    block = next(b for b in response.content if b.type == "tool_use")
    error = check(block.input)
    if error is None:
        first_try += 1
        repaired += 1
        print(f"  {question[:48]:50} ok")
        continue
    messages += [
        {"role": "assistant", "content": response.content},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "is_error": True,
                    "content": f"That query was rejected: {error}. Call build_query again with it fixed.",
                }
            ],
        },
    ]
    retry = client.messages.create(
        model=MODEL, max_tokens=2048, system=SYSTEM, messages=messages,
        tools=[TOOL], tool_choice={"type": "tool", "name": "build_query"},
    )
    cost["cache_read"] += retry.usage.cache_read_input_tokens or 0
    cost["input"] += retry.usage.input_tokens
    cost["output"] += retry.usage.output_tokens
    retry_block = next(b for b in retry.content if b.type == "tool_use")
    second = check(retry_block.input)
    if second is None:
        repaired += 1
        print(f"  {question[:48]:50} repaired ({error.split(';')[0][:44]})")
    else:
        print(f"  {question[:48]:50} STILL FAILS: {second[:60]}")
print(f"\n{MODEL}: first try {first_try}/{len(QUESTIONS)}, after repair {repaired}/{len(QUESTIONS)}")
print(f"tokens: {cost}")
