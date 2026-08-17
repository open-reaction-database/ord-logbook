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

"""What does the occurrence index buy, now that the pivots answer the other clause?

A structure quantifier the index refuses falls to the pivot rather than to the elements,
and the pivots are artifacts costing no memory -- so the question is what the index is
still worth against a corpus that has them.

Two routes, each in its own process: as it ships, and with the index refused so the
pivots take every quantifier. Row counts are compared, since a route that answers
differently is not a route.
"""

import json
import logging
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"
STRUCTURES = f"{HOME}/ord/structures/**/*.parquet"
PIVOTS = f"{HOME}/ord/pivots"

PYRIDINE = "c1ccncc1"
BENZENE_RING = "c1ccccc1"
BORONIC = "[#6]B(O)O"
CARBON = "c"


def _inputs(where):
    return {"op": "exists", "path": "inputs.components", "where": where}


def _solvent(smarts):
    return _inputs(
        {
            "op": "and",
            "clauses": [
                {"op": "substructure", "path": "smiles", "smarts": smarts},
                {
                    "op": "eq",
                    "path": "reaction_role",
                    "value": {"literal": "SOLVENT"},
                },
            ],
        }
    )


GOOD_YIELD = {
    "op": "exists",
    "path": "outcomes.products.measurements",
    "where": {
        "op": "and",
        "clauses": [
            {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
            {"op": "gt", "path": "percentage.value", "value": {"literal": 50}},
        ],
    },
}

HOT = {
    "op": "gt",
    "path": "conditions.temperature.setpoint_kelvin",
    "value": {"literal": 350},
}

REFLUX = {
    "op": "contains",
    "path": "notes.procedure_details",
    "value": {"literal": "reflux"},
}

WHITE_PRODUCT = {
    "op": "exists",
    "path": "outcomes.products",
    "where": {"op": "eq", "path": "isolated_color", "value": {"literal": "white"}},
}

QUERIES = {
    "pyridine solvent, above 350 K": {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), HOT]}
    },
    "pyridine solvent, yield > 50%": {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), GOOD_YIELD]}
    },
    "pyridine solvent, white product": {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), WHITE_PRODUCT]}
    },
    'pyridine solvent, "reflux" in the procedure': {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), REFLUX]}
    },
    "yields by product color (grouped)": {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), GOOD_YIELD]},
        "aggregate": {
            "group_by": ["conditions.stirring.type"],
            "measures": [{"fn": "count", "name": "reactions"}],
        },
    },
    "hottest with a yield (ordered, limited)": {
        "where": {"op": "and", "clauses": [_solvent(PYRIDINE), GOOD_YIELD]},
        "order_by": [{"key": "conditions.temperature.setpoint_kelvin"}],
        "limit": 25,
    },
    "boronic acid, pyridine solvent, yield > 50%": {
        "where": {
            "op": "and",
            "clauses": [
                _solvent(PYRIDINE),
                _inputs({"op": "substructure", "path": "smiles", "smarts": BORONIC}),
                GOOD_YIELD,
            ],
        }
    },
    "any aromatic carbon, yield > 50%": {
        "where": {
            "op": "and",
            "clauses": [
                _inputs({"op": "substructure", "path": "smiles", "smarts": CARBON}),
                GOOD_YIELD,
            ],
        }
    },
    "a benzene ring, yield > 50%": {
        "where": {
            "op": "and",
            "clauses": [
                _inputs(
                    {"op": "substructure", "path": "smiles", "smarts": BENZENE_RING}
                ),
                GOOD_YIELD,
            ],
        }
    },
    "not pyridine anywhere, with a yield": {
        "where": {
            "op": "and",
            "clauses": [
                {
                    "op": "not",
                    "clause": _inputs(
                        {"op": "substructure", "path": "smiles", "smarts": PYRIDINE}
                    ),
                },
                GOOD_YIELD,
            ],
        }
    },
}

ROUTES = ("index", "pivots")
RUNS = 3


def _measure(route: str) -> None:
    """Runs the query set on one route and prints the timings as JSON."""
    from ord_schema.search import execute, query

    if route == "pivots":
        execute._index_condition = lambda path, fields, allocate: None
    logging.disable(logging.INFO)
    with execute.Corpus(
        PROJECTIONS,
        STRUCTURES,
        resolver={}.__getitem__,
        require_current=False,
        pivots_dir=PIVOTS,
    ) as corpus:
        result = {"route": route, "queries": {}}
        for label, body in QUERIES.items():
            request = query.Query.model_validate(body)
            timings, rows = [], 0
            for _ in range(RUNS):
                start = time.perf_counter()
                table = corpus.search(request)
                timings.append(time.perf_counter() - start)
                rows = table.num_rows
            result["queries"][label] = {"timings": timings, "rows": rows}
        held = corpus._connection.execute(
            "SELECT coalesce(sum(memory_usage_bytes), 0) FROM duckdb_memory() "
            "WHERE tag = 'IN_MEMORY_TABLE'"
        ).fetchone()
        result["held"] = int(held[0] or 0)
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

    print(f"\n{'query':44s} " + " ".join(f"{route:>10s}" for route in results))
    for label in QUERIES:
        cells, counts = [], set()
        for result in results.values():
            measured = result["queries"][label]
            cells.append(f"{min(measured['timings'][1:]):9.3f}s")
            counts.add(measured["rows"])
        agree = "same" if len(counts) == 1 else f"DIFFERENT {sorted(counts)}"
        print(f"{label:44s} " + " ".join(cells) + f"  {agree}")
    print()
    for route, result in results.items():
        print(f"{route:10s} in-memory tables {result['held'] / 1024**3:.2f} G")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
