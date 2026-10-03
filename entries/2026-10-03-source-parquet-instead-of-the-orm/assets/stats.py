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

"""Times ord-interface's most-used-SMILES stats as search API aggregates."""

import os
import statistics
import time

from ord_schema.search import execute, query

ROOT = os.path.expanduser("~/ord/artifacts")
DATASETS = {"USPTO": "ord_dataset-1158e351757f315b93cbcbe7bc55f38e", "small": "ord_dataset-00005539a1e04c809a9a78647bea649c"}
LEVELS = {"inputs": "inputs.components", "products": "outcomes.products"}

with execute.Corpus(
    f"{ROOT}/projections/**/*.parquet", f"{ROOT}/structures/**/*.parquet",
    require_current=False, pivots_dir=f"{ROOT}/pivots", occurrences_dir=f"{ROOT}/occurrences",
) as corpus:
    for dataset, dataset_id in DATASETS.items():
        for kind, level in LEVELS.items():
            stats = query.Query.model_validate({
                "where": {"op": "eq", "path": "dataset_id", "value": {"literal": dataset_id}},
                "aggregate": {"over": level, "where": {"op": "not_null", "path": "smiles"},
                              "group_by": ["smiles"], "measures": [{"fn": "count", "name": "times_appearing"}]},
                "order_by": [{"key": "times_appearing", "descending": True}],
                "limit": 30,
            })
            start = time.perf_counter()
            table = corpus.search(stats)
            first = time.perf_counter() - start
            runs = []
            for _ in range(3):
                start = time.perf_counter()
                corpus.search(stats)
                runs.append(time.perf_counter() - start)
            top = table.to_pylist()[0]
            print(f"{dataset:6} {kind:9} rows={table.num_rows} first={first:.2f} s repeat={statistics.median(runs):.2f} s top={top['smiles'][:30]} x{top['times_appearing']}", flush=True)
