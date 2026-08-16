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

"""Can DuckDB's own caches stand in for the materialized narrow tables?

The narrow-table subsystem exists because reading a handful of leaves out of the
projection costs seconds where a materialized table costs tenths. If that cost is IO or
footer decoding, DuckDB already has caches for both -- the external file cache holds
file bytes, parquet_metadata_cache holds the footers -- and either would be free where
holding a column set costs gigabytes.

Each configuration is measured in its own process, so one run's caches cannot warm the
next one's. Within a process the query runs five times: the first pays whatever a cold
cache costs and the rest say what a warm one is worth.
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"

# Reaching one leaf apiece, so projection pushdown has every chance to make the read
# cheap; a narrow table would hold the whole top-level column either one sits under.
QUERIES = {
    "temperature": (
        "SELECT count(*) FROM reactions "
        "WHERE conditions.temperature.setpoint_kelvin > 300"
    ),
    "stirring": (
        "SELECT conditions.stirring.type, count(*) FROM reactions GROUP BY 1"
    ),
}

# name -> (settings, materialize)
CONFIGURATIONS = {
    "parquet, no caches": ({"enable_external_file_cache": "false"}, False),
    "parquet, file cache": ({"enable_external_file_cache": "true"}, False),
    "parquet, file+footer cache": (
        {"enable_external_file_cache": "true", "parquet_metadata_cache": "true"},
        False,
    ),
    "materialized column": ({}, True),
}

RUNS = 5


def _external_cache_bytes(connection) -> int:
    """Returns what DuckDB holds in its external file cache, in bytes."""
    row = connection.execute(
        "SELECT coalesce(sum(memory_usage_bytes), 0) FROM duckdb_memory() "
        "WHERE tag = 'EXTERNAL_FILE_CACHE'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _table_bytes(connection) -> int:
    """Returns what DuckDB holds in in-memory tables, in bytes."""
    row = connection.execute(
        "SELECT coalesce(sum(memory_usage_bytes), 0) FROM duckdb_memory() "
        "WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _measure(name: str) -> None:
    """Runs every query under one configuration and prints the timings as JSON."""
    import duckdb

    settings, materialize = CONFIGURATIONS[name]
    connection = duckdb.connect()
    for key, value in settings.items():
        connection.execute(f"SET {key}={value}")
    connection.execute(
        f"CREATE VIEW projected AS SELECT * FROM read_parquet('{PROJECTIONS}')"
    )
    result = {"name": name, "queries": {}}
    if materialize:
        start = time.perf_counter()
        connection.execute(
            "CREATE TABLE reactions AS SELECT reaction_id, conditions FROM projected"
        )
        result["build_seconds"] = time.perf_counter() - start
        result["held_bytes"] = _table_bytes(connection)
    else:
        connection.execute("CREATE VIEW reactions AS SELECT * FROM projected")
    for label, sql in QUERIES.items():
        timings = []
        for _ in range(RUNS):
            start = time.perf_counter()
            connection.execute(sql).fetchall()
            timings.append(time.perf_counter() - start)
        result["queries"][label] = timings
    result["file_cache_bytes"] = _external_cache_bytes(connection)
    connection.close()
    print("RESULT " + json.dumps(result), flush=True)


def main() -> None:
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
        return
    print(f"{'configuration':30s} {'query':14s} {'cold':>8s} {'warm':>8s} {'held':>10s}")
    for name in CONFIGURATIONS:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-u", __file__, name],
            capture_output=True,
            text=True,
            check=False,
        )
        line = next(
            (
                row
                for row in completed.stdout.splitlines()
                if row.startswith("RESULT ")
            ),
            None,
        )
        if line is None:
            print(f"{name}: FAILED\n{completed.stderr[-800:]}", flush=True)
            continue
        result = json.loads(line[len("RESULT ") :])
        held = result.get("held_bytes", result.get("file_cache_bytes", 0))
        for label, timings in result["queries"].items():
            warm = min(timings[1:])
            print(
                f"{name:30s} {label:14s} {timings[0]:7.3f}s {warm:7.3f}s "
                f"{held / 1024**3:9.2f}G",
                flush=True,
            )
        if "build_seconds" in result:
            print(f"{'':30s} {'(build)':14s} {result['build_seconds']:7.3f}s")


if __name__ == "__main__":
    main()
