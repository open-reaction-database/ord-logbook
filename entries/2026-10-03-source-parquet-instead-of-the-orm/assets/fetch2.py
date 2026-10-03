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

"""Projection/source row alignment, source verification cost, and two cheaper fetch routes."""

import collections
import concurrent.futures
import glob
import os
import random
import statistics
import time

import duckdb
import pyarrow.parquet as pq

from ord_schema import parquet
from ord_schema.artifacts import base

SOURCES = sorted(glob.glob(os.path.expanduser("~/ord/ord-data/data/*/*.parquet")))
PROJECTIONS = sorted(glob.glob(os.path.expanduser("~/ord/artifacts/projections/**/*.parquet"), recursive=True))

# 1. Do projections keep their source's row order, and do the stamps name these sources?
start = time.perf_counter()
digests = {parquet.DatasetView(path).md5(): path for path in SOURCES}
print(f"md5 of all {len(SOURCES)} sources: {time.perf_counter() - start:.1f} s", flush=True)
pairs, aligned = {}, 0
for projection in PROJECTIONS:
    source = digests.get(base.load_stamps(projection).source_md5)
    assert source is not None, f"{projection}: no local source has its stamped md5"
    pairs[projection] = source
    ids_p = pq.read_table(projection, columns=["reaction_id"]).column(0)
    ids_s = pq.read_table(source, columns=["reaction_id"]).column(0)
    aligned += ids_p.equals(ids_s)
print(f"projections whose stamped source is local: {len(pairs)}/{len(PROJECTIONS)}; row order identical: {aligned}/{len(pairs)}", flush=True)

# 2. Routes over the same samples as fetch.py.
connection = duckdb.connect()
locations = connection.execute(
    "SELECT reaction_id, filename, file_row_number FROM read_parquet($paths, filename=true, file_row_number=true)",
    {"paths": PROJECTIONS},
).fetchall()
where = {reaction_id: (pairs[filename], row) for reaction_id, filename, row in locations}
rng = random.Random(7)
samples = {f"random {n}": rng.sample(list(where), n) for n in (1, 100, 1000)}
files = {path: pq.ParquetFile(path) for path in SOURCES}
starts = {path: [0] for path in SOURCES}
for path, parquet_file in files.items():
    for group in range(parquet_file.num_row_groups - 1):
        starts[path].append(starts[path][-1] + parquet_file.metadata.row_group(group).num_rows)


def positional(ids, threads=8):
    """Fetch given (source, row) per ID, as a search could return them."""
    wanted = collections.defaultdict(list)
    for reaction_id in dict.fromkeys(ids):
        path, row = where[reaction_id]
        group = max(g for g, s in enumerate(starts[path]) if s <= row)
        wanted[(path, group)].append((reaction_id, row - starts[path][group]))

    def read(key):
        column = files[key[0]].read_row_group(key[1], columns=["reaction"]).column(0)
        return [(reaction_id, column[offset].as_py()) for reaction_id, offset in wanted[key]]

    with concurrent.futures.ThreadPoolExecutor(threads) as pool:
        found = dict(pair for pairs_ in pool.map(read, wanted) for pair in pairs_)
    return [found[reaction_id] for reaction_id in dict.fromkeys(ids)]


def direct_in_files(ids):
    """DuckDB direct, scanning only the sources the IDs come from."""
    paths = sorted({where[reaction_id][0] for reaction_id in ids})
    rows = connection.execute(
        "SELECT reaction_id, reaction FROM read_parquet($paths) WHERE reaction_id IN (SELECT unnest($ids))",
        {"paths": paths, "ids": list(ids)},
    ).fetchall()
    return rows


def lookup_rows(ids):
    """What finding (source, row) costs when the search did not return it."""
    return connection.execute(
        "SELECT reaction_id, filename, file_row_number FROM read_parquet($paths, filename=true, file_row_number=true) "
        "WHERE reaction_id IN (SELECT unnest($ids))",
        {"paths": PROJECTIONS, "ids": list(ids)},
    ).fetchall()


def timed(function):
    function()
    runs = []
    for _ in range(3):
        start = time.perf_counter()
        function()
        runs.append(time.perf_counter() - start)
    return round(statistics.median(runs), 3)


for name, ids in samples.items():
    assert positional(ids) == [blob for _, blob in sorted(direct_in_files(ids), key=lambda r: ids.index(r[0]))]
    print(f"{name:12} positional x8={timed(lambda: positional(ids))}  direct in files={timed(lambda: direct_in_files(ids))}  "
          f"row lookup over projections={timed(lambda: lookup_rows(ids))}", flush=True)
