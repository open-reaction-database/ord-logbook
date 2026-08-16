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

"""What each field of a pivot's element costs to hold, in the memory the budget counts.

The footers say a pruned ``workups`` element is a third of a gigabyte on disk, and the
build measures the same pivot at 4.40 GiB in memory. Something between the two is
charging far more than the data, and pruning is worth designing only against the figure
the budget actually spends.

Builds the pivot once and then re-materializes it a field at a time, so every reading is
a difference across one table and no reading pays for the unnest again.
"""

import json
import os
import sys
import time

HOME = os.path.expanduser("~")
PROJECTIONS = f"{HOME}/ord/projections/**/*.parquet"

LEVELS = (
    "workups",
    "outcomes.products",
    "outcomes.products.measurements",
    "inputs.components",
)


def _held(connection) -> int:
    """Returns what DuckDB holds in in-memory tables, in bytes."""
    row = connection.execute(
        "SELECT coalesce(sum(memory_usage_bytes), 0) FROM duckdb_memory() "
        "WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _measure(level_path: str) -> None:
    """Builds one pivot and prints what it and each of its element fields cost."""
    import duckdb
    import pyarrow as pa

    from ord_schema.artifacts import pivot

    level = pivot.LEVELS[level_path]
    connection = duckdb.connect()
    connection.execute(
        f"CREATE VIEW reactions AS SELECT * FROM read_parquet('{PROJECTIONS}')"
    )
    start = time.perf_counter()
    before = _held(connection)
    connection.execute(f"CREATE TABLE pivoted AS {pivot.select(level, 'reactions')}")
    whole = _held(connection) - before
    build = time.perf_counter() - start
    rows = connection.execute("SELECT count(*) FROM pivoted").fetchone()[0]

    fields = {}
    for field in level.element_type:
        base = _held(connection)
        connection.execute(
            f'CREATE TABLE part AS SELECT element."{field.name}" FROM pivoted'
        )
        fields[field.name] = _held(connection) - base
        connection.execute("DROP TABLE part")
    # The keys every row carries whatever the element holds.
    base = _held(connection)
    keys = ", ".join(["reaction_id", *level.ordinals])
    connection.execute(f"CREATE TABLE part AS SELECT {keys} FROM pivoted")
    key_bytes = _held(connection) - base
    connection.execute("DROP TABLE part")
    connection.close()

    print(
        "RESULT "
        + json.dumps(
            {
                "level": level_path,
                "rows": rows,
                "whole": whole,
                "build": build,
                "keys": key_bytes,
                "leaves": len(_leaves(level.element_type)),
                "fields": fields,
                "field_leaves": {
                    field.name: len(_leaves(field.type))
                    if pa.types.is_struct(field.type)
                    else 1
                    for field in level.element_type
                },
            }
        ),
        flush=True,
    )


def _leaves(dtype) -> list[str]:
    """Returns the dotted leaf paths of a struct type."""
    import pyarrow as pa

    found = []
    for field in dtype:
        if pa.types.is_struct(field.type):
            found.extend(f"{field.name}.{leaf}" for leaf in _leaves(field.type))
        else:
            found.append(field.name)
    return found


def main() -> None:
    import subprocess

    for level_path in LEVELS:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-u", __file__, level_path],
            capture_output=True,
            text=True,
            check=False,
        )
        line = next(
            (row for row in completed.stdout.splitlines() if row.startswith("RESULT ")),
            None,
        )
        if line is None:
            print(f"{level_path}: FAILED\n{completed.stderr[-1500:]}", flush=True)
            continue
        result = json.loads(line[len("RESULT ") :])
        print(
            f"\n{result['level']}: {result['rows']:,} rows, "
            f"{result['leaves']} leaves, {result['whole'] / 1024**3:.2f} GiB "
            f"in {result['build']:.0f}s "
            f"({result['whole'] / max(result['rows'], 1):.0f} B/row)",
            flush=True,
        )
        print(
            f"    {'reaction_id + ordinals':32s} "
            f"{result['keys'] / 1024**3:6.3f} GiB",
            flush=True,
        )
        for field, cost in sorted(
            result["fields"].items(), key=lambda item: -item[1]
        )[:12]:
            leaves = result["field_leaves"][field]
            print(
                f"    {field:32s} {cost / 1024**3:6.3f} GiB  "
                f"{leaves:3d} leaves  {cost / max(leaves, 1) / 1024**2:6.1f} MiB/leaf",
                flush=True,
            )


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
