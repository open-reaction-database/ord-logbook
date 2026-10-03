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

"""Times fetching serialized Reactions by ID from the source Parquet files.

direct   DuckDB reads the sources with the ID filter pushed into the scan.
indexed  an in-memory reaction_id -> (file, row group, offset) map built at open, then
         pyarrow reads only the row groups holding the requested IDs.
"""

import collections
import concurrent.futures
import glob
import json
import os
import random
import resource
import statistics
import sys
import time

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from ord_schema.proto import reaction_pb2
from ord_schema.search import execute, query

SOURCES = sorted(glob.glob(os.path.expanduser("~/ord/ord-data/data/*/*.parquet")))
ROOT = os.path.expanduser("~/ord/artifacts")


def rss_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # bytes on macOS


class Index:
    def __init__(self, paths):
        self.files = [pq.ParquetFile(path) for path in paths]
        self.where = {}
        for number, parquet_file in enumerate(self.files):
            for group in range(parquet_file.num_row_groups):
                ids = parquet_file.read_row_group(group, columns=["reaction_id"]).column(0)
                for offset, reaction_id in enumerate(ids.to_pylist()):
                    self.where.setdefault(reaction_id, (number, group, offset))

    def fetch(self, reaction_ids, threads=1):
        wanted = collections.defaultdict(list)
        for reaction_id in dict.fromkeys(reaction_ids):
            located = self.where.get(reaction_id)
            if located is not None:
                wanted[located[:2]].append((reaction_id, located[2]))

        def read(key):
            number, group = key
            column = self.files[number].read_row_group(group, columns=["reaction"]).column(0)
            return [(reaction_id, column[offset].as_py()) for reaction_id, offset in wanted[key]]

        found = {}
        if threads == 1:
            for key in wanted:
                found.update(read(key))
        else:
            with concurrent.futures.ThreadPoolExecutor(threads) as pool:
                for pairs in pool.map(read, wanted):
                    found.update(pairs)
        return [(reaction_id, found[reaction_id]) for reaction_id in dict.fromkeys(reaction_ids) if reaction_id in found], len(wanted)


def direct(connection, reaction_ids):
    rows = connection.execute(
        "SELECT reaction_id, reaction FROM read_parquet($paths) WHERE reaction_id IN (SELECT unnest($ids))",
        {"paths": SOURCES, "ids": list(reaction_ids)},
    ).fetchall()
    found = dict(rows)
    return [(reaction_id, found[reaction_id]) for reaction_id in dict.fromkeys(reaction_ids) if reaction_id in found]


def timed(function, repeats=3):
    start = time.perf_counter()
    result = function()
    first = time.perf_counter() - start
    again = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        again.append(time.perf_counter() - start)
    return result, first, statistics.median(again)


def check(pairs, expected):
    assert [reaction_id for reaction_id, _ in pairs] == list(dict.fromkeys(expected)), "order or membership differs"
    for reaction_id, blob in pairs[:50]:
        assert reaction_pb2.Reaction.FromString(blob).reaction_id == reaction_id


def main():
    out = {}
    before = rss_mib()
    start = time.perf_counter()
    index = Index(SOURCES)
    out["index"] = {"build_s": round(time.perf_counter() - start, 2), "ids": len(index.where), "max_rss_growth_mib": round(rss_mib() - before)}
    print("index", out["index"], flush=True)

    rng = random.Random(7)
    everything = list(index.where)
    samples = {f"random {n}": rng.sample(everything, n) for n in (1, 10, 100, 1000)}
    with execute.Corpus(
        f"{ROOT}/projections/**/*.parquet", f"{ROOT}/structures/**/*.parquet",
        require_current=False, pivots_dir=f"{ROOT}/pivots", occurrences_dir=f"{ROOT}/occurrences",
    ) as corpus:
        for name, where in {
            "amide SMARTS, first page": {"op": "reaction_smarts", "smarts": "C(=O)O.N>>C(=O)N"},
            "yield above 90%": {"op": "exists", "path": "outcomes.products.measurements", "where": {"op": "and", "clauses": [
                {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                {"op": "gt", "path": "percentage.value", "value": {"literal": 90}}]}},
            "one small dataset": {"op": "eq", "path": "dataset_id", "value": {"literal": "ord_dataset-00005539a1e04c809a9a78647bea649c"}},
        }.items():
            ids = corpus.search(query.Query.model_validate({"where": where})).column("reaction_id").to_pylist()
            samples[f"search: {name} ({len(ids)})"] = ids

    connection = duckdb.connect()
    for name, ids in samples.items():
        row = {}
        pairs, first, again = timed(lambda: direct(connection, ids))
        check(pairs, ids)
        row["direct"] = (round(first, 3), round(again, 3))
        for threads in (1, 8):
            (pairs, groups), first, again = timed(lambda: index.fetch(ids, threads))
            check(pairs, ids)
            row[f"indexed x{threads}"] = (round(first, 3), round(again, 3))
        row["row groups"] = groups
        row["MiB returned"] = round(sum(len(blob) for _, blob in pairs) / 2**20, 2)
        out[name] = row
        print(f"{name:42} " + "  ".join(f"{k}={v}" for k, v in row.items()), flush=True)
    json.dump(out, open("fetch.json", "w"), indent=1)


if __name__ == "__main__":
    main()
