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

"""Does caching the Parquet footers make the materialized column sets unnecessary?

The narrow-table subsystem exists because a query reaching a handful of leaves out of
the projection costs the better part of a second, and holding those columns in memory
brings it to milliseconds. That cost was never attributed. If it is footer parsing --
53 files, 442 leaves, re-decoded on every scan -- DuckDB's ``parquet_metadata_cache``
removes it for a few hundred megabytes across the whole corpus, where a materialized
column set costs gigabytes apiece.

Each configuration runs in its own process, since the caches under test are exactly
what one run would leave warm for the next. Queries go through a real ``Corpus``, so
what is measured is the route a caller takes rather than a hand-written scan.
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"
STRUCTURES = f"{HOME}/ord/structures/**/*.parquet"

# Scalar and aggregate queries only: these are what still reads the projection once the
# pivots answer the quantifiers, and so what the narrow tables are left to serve.
QUERIES = {
    "temperature filter": {
        "where": {
            "op": "gt",
            "path": "conditions.temperature.setpoint_kelvin",
            "value": {"literal": 350},
        }
    },
    "stirring group-by": {
        "aggregate": {
            "group_by": ["conditions.stirring.type"],
            "measures": [{"name": "n", "fn": "count"}],
        }
    },
    "two columns": {
        "where": {
            "op": "and",
            "clauses": [
                {
                    "op": "gt",
                    "path": "conditions.temperature.setpoint_kelvin",
                    "value": {"literal": 300},
                },
                {
                    "op": "eq",
                    "path": "provenance.city",
                    "value": {"literal": "Cambridge"},
                },
            ],
        }
    },
    "identifier scan": {
        "where": {
            "op": "contains",
            "path": "notes.safety_notes",
            "value": {"literal": "hood"},
        }
    },
}

GIGABYTE = 1024**3

# name -> (narrow_budget_bytes, footer cache)
CONFIGURATIONS = {
    "materialized, no footer cache": (4 * GIGABYTE, False),
    "no materialization, no footer cache": (0, False),
    "no materialization, footer cache": (0, True),
    "materialized, footer cache": (4 * GIGABYTE, True),
}

RUNS = 3


def _measure(name: str) -> None:
    """Runs every query under one configuration and prints the timings as JSON."""
    from ord_schema.search import execute, query

    budget, footer = CONFIGURATIONS[name]
    with execute.Corpus(
        PROJECTIONS,
        STRUCTURES,
        resolver={}.__getitem__,
        require_current=False,
        narrow_budget_bytes=budget,
    ) as corpus:
        if footer:
            corpus._connection.execute("SET GLOBAL parquet_metadata_cache=true")
        result = {"name": name, "queries": {}}
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
            "SELECT tag, sum(memory_usage_bytes) FROM duckdb_memory() "
            "WHERE tag IN ('IN_MEMORY_TABLE', 'OBJECT_CACHE', 'EXTERNAL_FILE_CACHE') "
            "GROUP BY 1"
        ).fetchall()
        result["held"] = {tag: int(value or 0) for tag, value in held}
    print("RESULT " + json.dumps(result), flush=True)


def main() -> None:
    print(
        f"{'configuration':36s} {'query':20s} {'cold':>8s} {'warm':>8s} "
        f"{'rows':>9s}",
        flush=True,
    )
    for name in CONFIGURATIONS:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-u", __file__, name],
            capture_output=True,
            text=True,
            check=False,
        )
        line = next(
            (row for row in completed.stdout.splitlines() if row.startswith("RESULT ")),
            None,
        )
        if line is None:
            print(f"{name}: FAILED\n{completed.stderr[-1500:]}", flush=True)
            continue
        result = json.loads(line[len("RESULT ") :])
        for label, measured in result["queries"].items():
            timings = measured["timings"]
            print(
                f"{name:36s} {label:20s} {timings[0]:7.3f}s "
                f"{min(timings[1:]):7.3f}s {measured['rows']:9,d}",
                flush=True,
            )
        held = " ".join(
            f"{tag.lower()} {value / GIGABYTE:.2f}G"
            for tag, value in sorted(result["held"].items())
            if value
        )
        print(f"{'':36s} held: {held or 'nothing'}\n", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
