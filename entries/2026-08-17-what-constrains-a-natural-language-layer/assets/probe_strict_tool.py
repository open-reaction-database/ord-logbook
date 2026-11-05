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

"""Does the strict-tool path have a bigger grammar budget than output_config.format?"""

import json
import pathlib
import sys

import anthropic
from anthropic.lib._parse._transform import transform_schema

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from stratify import stratify  # noqa: E402

from ord_schema.search import query  # noqa: E402

client = anthropic.Anthropic()
base = query.Query.model_json_schema()
for depth in (0, 1, 2, 4):
    schema = transform_schema(stratify(base, depth))
    tool = {
        "name": "build_query",
        "description": "Build an ORD search query.",
        "strict": True,
        "input_schema": schema,
    }
    size = f"{len(json.dumps(schema)) // 4:,} ~tokens"
    try:
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": "reactions above 350 K"}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "build_query"},
        )
    except anthropic.APIStatusError as error:
        message = json.loads(error.response.text)["error"]["message"]
        print(f"  strict tool, depth {depth}  {size:>16}  REFUSED: {message[:70]}")
    else:
        print(f"  strict tool, depth {depth}  {size:>16}  accepted")
