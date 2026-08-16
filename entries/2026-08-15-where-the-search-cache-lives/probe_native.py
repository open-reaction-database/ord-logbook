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

"""Could DuckDB's own buffer pool be the cache, instead of our narrow tables?

Writes the projection as a DuckDB database file, then runs the mixed query set against
it under a hard memory limit -- which is what a container would give it.
"""

import logging
import os
import pathlib
import time

import duckdb

from ord_schema.agent import execute, query

logging.disable(logging.INFO)

HOME = os.path.expanduser("~")
NATIVE = pathlib.Path("/tmp/ord_native.duckdb")  # noqa: S108 - a scratch measurement.


def _build() -> None:
    if NATIVE.exists():
        print(f"reusing {NATIVE} ({NATIVE.stat().st_size / 1024**3:.2f} GB)")
        return
    start = time.perf_counter()
    connection = duckdb.connect(str(NATIVE))
    try:
        # Row order is nothing this corpus promises, and preserving it is what makes
        # the write buffer the whole table rather than streaming it.
        connection.execute("SET preserve_insertion_order=false")
        connection.execute("SET memory_limit='8GB'")
        connection.execute(
            "CREATE TABLE reactions AS SELECT *, 0::BIGINT AS structure_offset "
            f"FROM read_parquet('{HOME}/ord/projections/**/*.parquet')"
        )
    finally:
        connection.close()
    print(
        f"wrote {NATIVE.stat().st_size / 1024**3:.2f} GB "
        f"in {time.perf_counter() - start:.0f}s"
    )


def main() -> None:
    _build()
    for limit in ("2GB", "6GB"):
        connection = duckdb.connect(str(NATIVE), read_only=True)
        connection.execute(f"SET memory_limit='{limit}'")
        rows = connection.execute("SELECT count(*) FROM reactions").fetchone()[0]
        print(f"\nmemory_limit={limit}, {rows} reactions", flush=True)
        for label, body in (
            (
                "yield > 50%",
                {
                    "where": {
                        "op": "exists",
                        "path": "outcomes.products.measurements",
                        "where": {
                            "op": "and",
                            "clauses": [
                                {
                                    "op": "eq",
                                    "path": "type",
                                    "value": {"literal": "YIELD"},
                                },
                                {
                                    "op": "gt",
                                    "path": "percentage.value",
                                    "value": {"literal": 50},
                                },
                            ],
                        },
                    }
                },
            ),
            (
                "a white product",
                {
                    "where": {
                        "op": "exists",
                        "path": "outcomes.products",
                        "where": {
                            "op": "eq",
                            "path": "isolated_color",
                            "value": {"literal": "white"},
                        },
                    }
                },
            ),
            (
                "above 350 K",
                {
                    "where": {
                        "op": "gt",
                        "path": "conditions.temperature.setpoint_kelvin",
                        "value": {"literal": 350},
                    }
                },
            ),
        ):
            compiled = query.compile_query(query.Query.model_validate(body))
            best = None
            for _ in range(3):
                start = time.perf_counter()
                table = connection.execute(compiled.sql).fetch_arrow_table()
                spent = time.perf_counter() - start
                best = spent if best is None else min(best, spent)
            print(f"  {label}: {best:.2f}s ({table.num_rows} rows)", flush=True)
        connection.close()
    print(f"\nfor comparison, in-memory narrow tables answered these in 0.2-0.6s")
    print(f"and Parquet without a narrow table in 3-5s")
    print(f"({execute._format_bytes(NATIVE.stat().st_size)} on disk)")


if __name__ == "__main__":
    main()
