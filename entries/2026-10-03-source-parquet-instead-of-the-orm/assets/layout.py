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

"""Row-group layout of the source Parquet files."""

import glob
import os
import statistics

import pyarrow.parquet as pq

paths = sorted(glob.glob(os.path.expanduser("~/ord/ord-data/data/*/*.parquet")))
rows = groups = 0
compressed, uncompressed, per_group = 0, 0, []
largest = None
for path in paths:
    metadata = pq.ParquetFile(path).metadata
    rows += metadata.num_rows
    groups += metadata.num_row_groups
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        column = group.column(1)  # reaction
        assert column.path_in_schema == "reaction"
        compressed += column.total_compressed_size
        uncompressed += column.total_uncompressed_size
        per_group.append((column.total_compressed_size, group.num_rows))
    if largest is None or metadata.num_rows > largest[1]:
        largest = (os.path.basename(path), metadata.num_rows, metadata.num_row_groups, os.path.getsize(path))
print(f"files {len(paths)} rows {rows:,} row groups {groups:,}")
print(f"reaction column: {compressed / 2**20:,.0f} MiB compressed, {uncompressed / 2**20:,.0f} MiB uncompressed")
sizes = sorted(size for size, _ in per_group)
print(f"compressed bytes per row group: median {statistics.median(sizes) / 2**10:,.0f} KiB, p90 {sizes[int(0.9 * len(sizes))] / 2**10:,.0f} KiB, max {sizes[-1] / 2**10:,.0f} KiB")
print(f"rows per row group: {sorted(set(n for _, n in per_group))[-3:]} (largest values)")
print(f"compression codec: {pq.ParquetFile(paths[0]).metadata.row_group(0).column(1).compression}")
print("largest file:", largest)
