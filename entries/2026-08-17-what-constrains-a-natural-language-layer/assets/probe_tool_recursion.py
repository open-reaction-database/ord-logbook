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

"""Do tool input schemas accept the recursion that output_config.format refuses?

Three shapes, cheapest question that still needs a nested predicate: a forced tool call
over the grammar as pydantic writes it, the same with strict on and the SDK's own
closing transform applied, and -- for reference -- what the model actually produces.
"""

import json

import anthropic
from anthropic.lib._parse._transform import transform_schema

from ord_schema.search import query, schema

QUESTION = "reactions using pyridine as the solvent with a yield above 50%"
SYSTEM = [
    {
        "type": "text",
        "text": (
            "You translate chemistry questions into ORD search queries. The corpus "
            "schema, as an indented type tree in DuckDB's types:\n\n" + schema.describe()
        ),
        "cache_control": {"type": "ephemeral"},
    }
]
RAW = query.Query.model_json_schema()

client = anthropic.Anthropic()
for label, input_schema, strict in (
    ("tool, as pydantic writes it", RAW, False),
    ("tool, strict + closed", transform_schema(json.loads(json.dumps(RAW))), True),
):
    tool: dict = {
        "name": "build_query",
        "description": "Build an ORD search query from the user's question.",
        "input_schema": input_schema,
    }
    if strict:
        tool["strict"] = True
    print(f"\n=== {label}")
    try:
        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": QUESTION}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "build_query"},
        )
    except anthropic.APIStatusError as error:
        print(f"  refused: {error.status_code} {str(error)[:220]}")
        continue
    block = next(b for b in response.content if b.type == "tool_use")
    print("  accepted. tool_use.input:")
    print(json.dumps(block.input, indent=2)[:900])
    try:
        parsed = query.Query.model_validate(block.input)
    except Exception as error:  # noqa: BLE001 -- the probe reports whatever it hits.
        print(f"  pydantic REJECTED it: {type(error).__name__}: {str(error)[:200]}")
    else:
        print(f"  pydantic accepted it: {parsed.where.op}")
    usage = response.usage
    print(
        f"  input={usage.input_tokens} cache_write={usage.cache_creation_input_tokens} "
        f"cache_read={usage.cache_read_input_tokens} output={usage.output_tokens}"
    )
