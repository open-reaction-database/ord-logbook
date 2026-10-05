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

"""Dump every field and enum value reachable from ord's Reaction and Dataset messages."""

import json
import sys

from google.protobuf import descriptor
from ord_schema.proto import dataset_pb2, reaction_pb2

TYPE_NAMES = {v: k for k, v in descriptor.FieldDescriptor.__dict__.items() if k.startswith("TYPE_")}


def walk(message_descriptor, seen, out):
    if message_descriptor.full_name in seen:
        return
    seen.add(message_descriptor.full_name)
    for field in message_descriptor.fields:
        target = field.message_type.full_name if field.message_type else (field.enum_type.full_name if field.enum_type else "")
        out["fields"][f"{message_descriptor.full_name}.{field.name}"] = {
            "number": field.number,
            "type": TYPE_NAMES[field.type],
            "repeated": field.label == descriptor.FieldDescriptor.LABEL_REPEATED,
            "target": target,
            "oneof": field.containing_oneof.name if field.containing_oneof else None,
        }
        if field.message_type:
            walk(field.message_type, seen, out)
        if field.enum_type:
            for value in field.enum_type.values:
                out["enums"][f"{field.enum_type.full_name}.{value.name}"] = value.number
    for enum_type in message_descriptor.enum_types:
        for value in enum_type.values:
            out["enums"][f"{enum_type.full_name}.{value.name}"] = value.number


out = {"fields": {}, "enums": {}}
seen = set()
walk(reaction_pb2.Reaction.DESCRIPTOR, seen, out)
walk(dataset_pb2.Dataset.DESCRIPTOR, seen, out)
json.dump(out, sys.stdout, indent=1, sort_keys=True)
