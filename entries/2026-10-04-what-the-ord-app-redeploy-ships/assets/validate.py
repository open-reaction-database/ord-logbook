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

"""Validate the corpus as the app does and write per-reaction errors and warnings."""

import json
import pathlib
import sys

import ord_schema
from ord_schema.proto import reaction_pb2
from ord_schema.validations import ValidationOptions, validate_message

options = ValidationOptions(require_provenance=True)
results = {}
for path in sorted(pathlib.Path("corpus").glob("*.bin")):
    data = path.read_bytes()
    offset = index = 0
    while offset < len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        reaction = reaction_pb2.Reaction.FromString(data[offset + 4 : offset + 4 + size])
        offset += 4 + size
        output = validate_message(reaction, raise_on_error=False, options=options)
        results[f"{path.stem}/{index}"] = {"errors": sorted(output.errors), "warnings": sorted(output.warnings)}
        index += 1
json.dump(results, open(sys.argv[1], "w"), indent=0, sort_keys=True)
print(getattr(ord_schema, "__version__", "?"), len(results))
