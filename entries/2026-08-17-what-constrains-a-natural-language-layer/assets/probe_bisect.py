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

"""Which part of the grammar makes the compiled decoding grammar too large?"""

import json
import pathlib
import sys

import anthropic
from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stratify import stratify  # noqa: E402

from ord_schema.search import query  # noqa: E402


class Tiny(BaseModel):
    name: str
    count: int


def sized(schema: dict) -> str:
    return f"{len(json.dumps(schema)) // 4:,} ~tokens"


client = anthropic.Anthropic()
cases = [
    ("a tiny two-field object", transform_schema(Tiny.model_json_schema())),
    ("one comparison predicate", transform_schema(query.Comparison.model_json_schema())),
    ("one quantifier", transform_schema(query.Quantifier.model_json_schema())),
    ("Query, stratified depth 0", transform_schema(stratify(query.Query.model_json_schema(), 0))),
    ("Query, stratified depth 1", transform_schema(stratify(query.Query.model_json_schema(), 1))),
]
for label, schema in cases:
    try:
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": "reactions above 350 K"}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIStatusError as error:
        message = json.loads(error.response.text)["error"]["message"]
        print(f"  {label:32} {sized(schema):>16}  REFUSED: {message[:80]}")
    else:
        print(f"  {label:32} {sized(schema):>16}  accepted")
