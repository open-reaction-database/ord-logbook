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

"""Does a stratified grammar unlock structured outputs, and can a cheap model hit it?

Same five questions as the tool-call probe, but the model is handed an acyclic schema
and constrained by output_config.format rather than asked to call a tool.
"""

import json
import pathlib
import sys

import anthropic
from anthropic.lib._parse._transform import transform_schema

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stratify import stratify  # noqa: E402

from ord_schema.search import query, schema  # noqa: E402

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
            "You translate chemistry questions into ORD search queries. The corpus "
            "schema, as an indented type tree in DuckDB's types:\n\n" + schema.describe()
        ),
        "cache_control": {"type": "ephemeral"},
    }
]
DEPTH = int(sys.argv[1]) if len(sys.argv) > 1 else 4
MODEL = sys.argv[2] if len(sys.argv) > 2 else "claude-haiku-4-5"
STRATIFIED = transform_schema(stratify(query.Query.model_json_schema(), DEPTH))

client = anthropic.Anthropic()
print(f"=== {MODEL}, stratified depth {DEPTH} "
      f"({len(json.dumps(STRATIFIED))//4:,} ~tokens)")
tallies = {"parses": 0, "compiles": 0}
cost = {"cache_write": 0, "cache_read": 0, "input": 0, "output": 0}
for question in QUESTIONS:
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM,
            messages=[{"role": "user", "content": question}],
            output_config={"format": {"type": "json_schema", "schema": STRATIFIED}},
        )
    except anthropic.APIStatusError as error:
        print(f"  refused: {error.status_code} {str(error)[:300]}")
        break
    usage = response.usage
    cost["cache_write"] += usage.cache_creation_input_tokens or 0
    cost["cache_read"] += usage.cache_read_input_tokens or 0
    cost["input"] += usage.input_tokens
    cost["output"] += usage.output_tokens
    text = next(b.text for b in response.content if b.type == "text")
    note = []
    try:
        parsed = query.Query.model_validate(json.loads(text))
    except Exception as error:  # noqa: BLE001 -- scoring, not handling.
        note.append(f"parse FAILED: {str(error)[:90]}")
    else:
        tallies["parses"] += 1
        try:
            query.compile_query(parsed)
        except Exception as error:  # noqa: BLE001
            note.append(f"compile FAILED: {str(error)[:90]}")
        else:
            tallies["compiles"] += 1
            note.append("compiles")
    print(f"  {question[:52]:54} {' | '.join(note)}")
print(f"  tallies (of {len(QUESTIONS)}): {tallies}")
print(f"  tokens: {cost}")
