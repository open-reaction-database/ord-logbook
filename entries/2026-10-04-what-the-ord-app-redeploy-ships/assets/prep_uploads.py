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

"""Pick three ord-data datasets by size and write each in every upload format."""

import gzip
import json
import pathlib
import shutil
import sys

import pyarrow.parquet as pq
from google.protobuf import json_format, text_format
from ord_schema import parquet

DATA = pathlib.Path(sys.argv[1])  # ord-data's data/ directory
OUT = pathlib.Path("uploads")
sizes = sorted((pq.ParquetFile(p).metadata.num_rows, p) for p in DATA.glob("*/*.parquet"))
picks = {"small": sizes[len(sizes) // 4], "medium": sizes[len(sizes) * 3 // 4], "large": sizes[-3]}
manifest = {}
for label, (rows, path) in picks.items():
    dataset = parquet.load_dataset(path)
    stem = OUT / label
    data = dataset.SerializeToString()
    pathlib.Path(f"{stem}.pb").write_bytes(data)
    pathlib.Path(f"{stem}.pb.gz").write_bytes(gzip.compress(data))
    pathlib.Path(f"{stem}.pbtxt").write_text(text_format.MessageToString(dataset))
    pathlib.Path(f"{stem}.json").write_text(json_format.MessageToJson(dataset))
    shutil.copy(path, f"{stem}.parquet")
    manifest[label] = {"source": path.name, "reactions": len(dataset.reactions), "name": dataset.name}
    print(label, rows, path.name, {s: pathlib.Path(f"{stem}{s}").stat().st_size // 1024 for s in (".pb", ".pb.gz", ".pbtxt", ".json", ".parquet")})
json.dump(manifest, open(OUT / "manifest.json", "w"), indent=1)
