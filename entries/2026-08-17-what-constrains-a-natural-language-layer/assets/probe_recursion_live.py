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

"""Does the API accept a recursive json_schema output format? Needs a real key.

    ANTHROPIC_API_KEY=sk-... uv run --with anthropic python probe_recursion_live.py

Prints the validated Query the model produced, or the error the server returned.
"""

import json

import anthropic

from ord_schema.search import query, schema

SYSTEM = (
    "You translate chemistry questions into ORD search queries. The corpus schema, "
    "as an indented type tree in DuckDB's types:\n\n" + schema.describe()
)

client = anthropic.Anthropic()
try:
    response = client.messages.parse(
        model="claude-opus-5",
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[
            {
                "role": "user",
                "content": "reactions using pyridine as the solvent with a yield above 50%",
            }
        ],
        output_format=query.Query,
    )
except anthropic.APIStatusError as error:
    print(f"server refused it: {error.status_code} {str(error)[:400]}")
else:
    print("accepted. parsed_output:")
    print(json.dumps(response.parsed_output.model_dump(exclude_none=True), indent=2))
    usage = response.usage
    print(
        f"\ninput={usage.input_tokens} "
        f"cache_write={usage.cache_creation_input_tokens} "
        f"cache_read={usage.cache_read_input_tokens} output={usage.output_tokens}"
    )
