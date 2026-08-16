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

"""Can a pivot answer what the occurrence index answers, now that pivots are artifacts?

The index was kept because it is 130 MB where the pivots it would replace were gigabytes.
As artifacts the pivots cost no memory at all, so the measurement that settled it no
longer holds and the question is open again.

The structure predicate compiles to a bit test on ``element.structure_id`` plus the
row's ``structure_offset``. Inside a pivot's semi-join that offset is unqualified and
binds to the correlated reaction, which is in exactly one projection file -- so it should
already be the right offset. Whether it is, and what the route costs, is what this asks.

Three routes over one query set: the index as shipped, the index refused so the pivots
take it, and both refused so the elements do. Row counts are compared across all three,
since a route that answers differently is not a route.
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"
STRUCTURES = f"{HOME}/ord/structures/**/*.parquet"
PIVOTS = f"{HOME}/ord/pivots"

RESOLVER = {"pyridine": "c1ccncc1", "ethanol": "CCO"}

QUERIES = {
    "pyridine anywhere": {
        "op": "exists",
        "path": "inputs.components",
        "where": {"op": "substructure", "path": "smiles", "compound": "pyridine"},
    },
    "pyridine as the solvent": {
        "op": "exists",
        "path": "inputs.components",
        "where": {
            "op": "and",
            "clauses": [
                {"op": "substructure", "path": "smiles", "compound": "pyridine"},
                {
                    "op": "eq",
                    "path": "reaction_role",
                    "value": {"literal": "SOLVENT"},
                },
            ],
        },
    },
    "pyridine solvent, above 350 K": {
        "op": "and",
        "clauses": [
            {
                "op": "exists",
                "path": "inputs.components",
                "where": {
                    "op": "and",
                    "clauses": [
                        {
                            "op": "substructure",
                            "path": "smiles",
                            "compound": "pyridine",
                        },
                        {
                            "op": "eq",
                            "path": "reaction_role",
                            "value": {"literal": "SOLVENT"},
                        },
                    ],
                },
            },
            {
                "op": "gt",
                "path": "conditions.temperature.setpoint_kelvin",
                "value": {"literal": 350},
            },
        ],
    },
    "a pyridine product": {
        "op": "exists",
        "path": "outcomes.products",
        "where": {"op": "substructure", "path": "smiles", "compound": "pyridine"},
    },
}

GIGABYTE = 1024**3

# name -> (offer the index, offer the pivots)
ROUTES = {
    "index": (True, True),
    "pivots": (False, True),
    "elements": (False, False),
}

RUNS = 3


def _measure(route: str) -> None:
    """Runs the query set on one route and prints the timings as JSON."""
    import contextlib

    from ord_schema.search import execute, query

    offer_index, offer_pivots = ROUTES[route]
    if not offer_index:
        execute._index_condition = lambda path, fields, allocate: None
    if not offer_pivots:

        @contextlib.contextmanager
        def _no_pivot(self, path):
            del self, path
            yield None

        execute.Corpus._pivoted_table = _no_pivot  # type: ignore[method-assign]
    with execute.Corpus(
        PROJECTIONS,
        STRUCTURES,
        resolver=RESOLVER.__getitem__,
        require_current=False,
        pivots_dir=PIVOTS if offer_pivots else None,
    ) as corpus:
        result = {"route": route, "queries": {}}
        for label, where in QUERIES.items():
            request = query.Query.model_validate({"where": where})
            timings, rows = [], 0
            for _ in range(RUNS):
                start = time.perf_counter()
                table = corpus.search(request)
                timings.append(time.perf_counter() - start)
                rows = table.num_rows
            result["queries"][label] = {"timings": timings, "rows": rows}
        held = corpus._connection.execute(
            "SELECT tag, sum(memory_usage_bytes) FROM duckdb_memory() "
            "WHERE tag = 'IN_MEMORY_TABLE' GROUP BY 1"
        ).fetchall()
        result["held"] = {tag: int(value or 0) for tag, value in held}
    print("RESULT " + json.dumps(result), flush=True)


def main() -> None:
    results = {}
    for route in ROUTES:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-u", __file__, route],
            capture_output=True,
            text=True,
            check=False,
        )
        line = next(
            (row for row in completed.stdout.splitlines() if row.startswith("RESULT ")),
            None,
        )
        if line is None:
            print(f"{route}: FAILED\n{completed.stderr[-2000:]}", flush=True)
            continue
        results[route] = json.loads(line[len("RESULT ") :])
        print(f"{route} done", flush=True)

    print(f"\n{'query':32s} " + " ".join(f"{route:>10s}" for route in results))
    for label in QUERIES:
        cells, counts = [], set()
        for result in results.values():
            measured = result["queries"][label]
            cells.append(f"{min(measured['timings'][1:]):9.3f}s")
            counts.add(measured["rows"])
        agree = "same" if len(counts) == 1 else f"DIFFERENT {sorted(counts)}"
        rows = next(iter(counts))
        print(f"{label:32s} " + " ".join(cells) + f"  {rows:9,d}  {agree}")
    print()
    for route, result in results.items():
        held = sum(result["held"].values())
        print(f"{route:10s} in-memory tables {held / GIGABYTE:.2f} G")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
