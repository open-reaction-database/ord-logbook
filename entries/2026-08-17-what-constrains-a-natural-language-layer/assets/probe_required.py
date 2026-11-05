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

"""Does requiring every property bring the grammar under the compiler's budget?"""

import copy
import json
import pathlib
import sys

import anthropic

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from require_all import require_all  # noqa: E402
from stratify import stratify  # noqa: E402

from ord_schema.search import query  # noqa: E402

client = anthropic.Anthropic()
base = query.Query.model_json_schema()
for depth in range(0, 6):
    schema = require_all(stratify(copy.deepcopy(base), depth), strip_descriptions=True)
    size = f"{len(json.dumps(schema)) // 4:,} ~tokens"
    try:
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{"role": "user", "content": "reactions above 350 K"}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIStatusError as error:
        message = json.loads(error.response.text)["error"]["message"]
        print(f"  depth {depth}  {size:>14}  REFUSED: {message[:78]}")
    else:
        print(f"  depth {depth}  {size:>14}  ACCEPTED")
