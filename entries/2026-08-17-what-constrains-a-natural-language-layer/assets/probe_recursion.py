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

"""What does the SDK send for a recursive output_format, and does it object first?

Captures the request body with a mock transport rather than a live call, so the
client-side half of the question is settled without a key: whether the SDK accepts a
self-referencing pydantic model at all, and what JSON Schema it puts on the wire.
"""

import json

import anthropic
import httpx

from ord_schema.search import query

CANNED = {
    "id": "msg_probe",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-5",
    "content": [{"type": "text", "text": "{}"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
sent = {}


def handler(request: httpx.Request) -> httpx.Response:
    sent["body"] = json.loads(request.content)
    return httpx.Response(200, json=CANNED)


client = anthropic.Anthropic(
    api_key="probe-not-a-real-key",
    http_client=httpx.Client(transport=httpx.MockTransport(handler)),
)

print("anthropic SDK:", anthropic.__version__)
for label, call in (
    (
        "messages.parse(output_format=Query)",
        lambda: client.messages.parse(
            model="claude-opus-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "pyridine as solvent"}],
            output_format=query.Query,
        ),
    ),
    (
        "messages.create(tools=[strict build_query])",
        lambda: client.messages.create(
            model="claude-opus-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "pyridine as solvent"}],
            tools=[
                {
                    "name": "build_query",
                    "description": "Build a search query.",
                    "strict": True,
                    "input_schema": query.Query.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "build_query"},
        ),
    ),
):
    sent.clear()
    print(f"\n=== {label}")
    try:
        call()
    except Exception as error:  # noqa: BLE001 -- the probe reports whatever it hits.
        print(f"  raised {type(error).__name__}: {str(error)[:200]}")
    body = sent.get("body")
    if body is None:
        print("  nothing reached the wire")
        continue
    schema = None
    if "output_config" in body:
        schema = body["output_config"].get("format", {}).get("schema")
        print("  output_config.format keys:", sorted(body["output_config"]["format"]))
    elif "tools" in body:
        schema = body["tools"][0].get("input_schema")
        print("  tool keys:", sorted(body["tools"][0]))
    if schema is None:
        print("  no schema on the wire")
        continue
    text = json.dumps(schema)
    print(f"  schema on the wire: {len(text)} chars, $defs={len(schema.get('$defs', {}))}")
    print(f"  contains $ref: {'$ref' in text}, refs={text.count('#/$defs/')}")
    print(f"  additionalProperties present: {text.count('additionalProperties')}")
