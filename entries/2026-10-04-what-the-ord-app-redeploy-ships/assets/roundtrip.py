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

"""Compare downloaded datasets with the uploaded originals, reaction by reaction."""

import collections
import pathlib

from google.protobuf import json_format, text_format
from ord_schema import parquet
from ord_schema.proto import dataset_pb2


def load(path):
    if path.suffix == ".parquet":
        return parquet.load_dataset(path)
    data = path.read_bytes()
    if path.suffix == ".binpb":
        return dataset_pb2.Dataset.FromString(data)
    if path.suffix == ".json":
        return json_format.Parse(data, dataset_pb2.Dataset())
    return text_format.Parse(data.decode(), dataset_pb2.Dataset())


def diff_fields(a, b, prefix=""):
    out = []
    for field in set(f.name for f, _ in a.ListFields()) | set(f.name for f, _ in b.ListFields()):
        if getattr(a, field) != getattr(b, field):
            out.append(prefix + field)
    return out


for label in ("small", "medium"):
    original = dataset_pb2.Dataset.FromString(pathlib.Path(f"uploads/{label}.pb").read_bytes())
    by_id = {r.reaction_id: r for r in original.reactions}
    for path in sorted(pathlib.Path("downloads").glob(f"{label}-*")):
        if path.stat().st_size == 0:
            continue
        try:
            downloaded = load(path)
        except Exception as error:
            print(f"{path.name:32s} PARSE FAILED {type(error).__name__}: {str(error)[:80]}")
            continue
        differing = collections.Counter()
        missing = 0
        for reaction in downloaded.reactions:
            source = by_id.get(reaction.reaction_id)
            if source is None:
                missing += 1
                continue
            for field in diff_fields(source, reaction):
                differing[field] += 1
        print(f"{path.name:32s} reactions={len(downloaded.reactions)}/{len(original.reactions)} unmatched_ids={missing} differing={dict(differing)} dataset_fields_differ={diff_fields(original, downloaded, '')[:6]}")
