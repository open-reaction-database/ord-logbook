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

"""Does a pivot held as an artifact answer as fast as one held in memory?

The in-process build is what makes a wide level expensive: the ``workups`` pivot is 4.40
GiB, over the default budget, so it is refused and the projection answers instead. A
pivot read from Parquet costs no budget at all -- the corpus publishes a view -- so if a
view answers as fast as a table, holding pivots stops being a memory question and
pruning them further is only a disk-size one.

Three routes, each in its own process so no cache is shared: artifacts, an in-memory
build with a budget large enough to keep every level, and the elements. Row counts are
compared across all three, since a route that answers differently is not a route.
"""

import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"
STRUCTURES = f"{HOME}/ord/structures/**/*.parquet"
PIVOTS = f"{HOME}/ord/pivots"

LEVELS = (
    "workups",
    "outcomes.products",
    "outcomes.products.measurements",
    "inputs.components",
)

QUERIES = {
    "a white product": {
        "op": "exists",
        "path": "outcomes.products",
        "where": {"op": "eq", "path": "isolated_color", "value": {"literal": "white"}},
    },
    "yield > 50%": {
        "op": "exists",
        "path": "outcomes.products.measurements",
        "where": {
            "op": "and",
            "clauses": [
                {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                {"op": "gt", "path": "percentage.value", "value": {"literal": 50}},
            ],
        },
    },
    "every product is desired": {
        "op": "forall",
        "path": "outcomes.products",
        "where": {
            "op": "eq",
            "path": "is_desired_product",
            "value": {"literal": True},
        },
    },
    "not a yield above 50%": {
        "op": "not",
        "clause": {
            "op": "exists",
            "path": "outcomes.products.measurements",
            "where": {
                "op": "and",
                "clauses": [
                    {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                    {"op": "gt", "path": "percentage.value", "value": {"literal": 50}},
                ],
            },
        },
    },
    "an extraction workup": {
        "op": "exists",
        "path": "workups",
        "where": {"op": "eq", "path": "type", "value": {"literal": "EXTRACTION"}},
    },
    "reflux in a workup": {
        "op": "exists",
        "path": "workups",
        "where": {"op": "contains", "path": "details", "value": {"literal": "reflux"}},
    },
    "a solvent input": {
        "op": "exists",
        "path": "inputs.components",
        "where": {
            "op": "eq",
            "path": "reaction_role",
            "value": {"literal": "SOLVENT"},
        },
    },
    "above 350 K": {
        "op": "gt",
        "path": "conditions.temperature.setpoint_kelvin",
        "value": {"literal": 350},
    },
}

GIGABYTE = 1024**3

# name -> (pivots_dir, budget, warm the pivots first)
ROUTES = {
    "artifacts": (PIVOTS, 4 * GIGABYTE, True),
    "memory": (None, 14 * GIGABYTE, True),
    "elements": (None, 4 * GIGABYTE, False),
}

RUNS = 3


@contextlib.contextmanager
def _no_pivot(self, path: str) -> Iterator[str | None]:
    """Stands in for ``Corpus._pivoted_table``, leaving every quantifier to the rows."""
    del self, path
    yield None


def _measure(route: str) -> None:
    """Runs the query set on one route and prints the timings as JSON."""
    from ord_schema.search import execute, query

    pivots_dir, budget, warm = ROUTES[route]
    if not warm:
        execute.Corpus._pivoted_table = _no_pivot  # type: ignore[method-assign]
    with execute.Corpus(
        PROJECTIONS,
        STRUCTURES,
        resolver={}.__getitem__,
        require_current=False,
        narrow_budget_bytes=budget,
        pivots_dir=pivots_dir,
    ) as corpus:
        result = {"route": route, "queries": {}, "pivots": {}}
        if warm:
            # Charged once here rather than to whichever query asked first.
            for level in LEVELS:
                start = time.perf_counter()
                with corpus._pivoted_table(level) as name:
                    result["pivots"][level] = {
                        "seconds": time.perf_counter() - start,
                        "held": name is not None,
                    }
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
            "WHERE tag IN ('IN_MEMORY_TABLE', 'OBJECT_CACHE', 'EXTERNAL_FILE_CACHE') "
            "GROUP BY 1"
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

    print(f"\n{'query':28s} " + " ".join(f"{route:>12s}" for route in results))
    for label in QUERIES:
        cells, counts = [], set()
        for result in results.values():
            measured = result["queries"][label]
            cells.append(f"{min(measured['timings'][1:]):11.3f}s")
            counts.add(measured["rows"])
        agree = "same" if len(counts) == 1 else f"DIFFERENT {sorted(counts)}"
        print(f"{label:28s} " + " ".join(cells) + f"  {agree}")

    print()
    for route, result in results.items():
        held = " ".join(
            f"{tag.lower()} {value / GIGABYTE:.2f}G"
            for tag, value in sorted(result["held"].items())
            if value
        )
        print(f"{route:12s} held: {held or 'nothing'}")
        for level, measured in result["pivots"].items():
            state = "held" if measured["held"] else "REFUSED"
            print(f"    {level:34s} {measured['seconds']:8.1f}s  {state}")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
