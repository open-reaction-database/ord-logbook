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

"""Report peak RSS after parsing the large dataset and serializing it one way."""

import pathlib
import resource
import sys

import google.protobuf
from google.protobuf import json_format, text_format
from ord_schema.proto import dataset_pb2

dataset = dataset_pb2.Dataset.FromString(pathlib.Path("uploads/large.pb").read_bytes())
after_parse = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
kind = sys.argv[1]
if kind == "json":
    data = json_format.MessageToJson(dataset).encode()
elif kind == "txtpb":
    data = text_format.MessageToString(dataset, as_utf8=True).encode()
else:
    data = dataset.SerializeToString()
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
print(f"protobuf {google.protobuf.__version__} {kind}: parse peak {after_parse:.0f} MB, total peak {peak:.0f} MB, output {len(data) / 2**20:.0f} MB")
