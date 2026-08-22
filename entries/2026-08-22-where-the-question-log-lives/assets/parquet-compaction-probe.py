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

"""Whether a question log survives compaction with its translations nested.

The log records a model-authored ``Query`` per attempt. That value is recursive and
differently shaped from record to record, so compacting a month of JSON into Parquet
means DuckDB inferring a struct type from whatever shapes that month happened to hold.
This asks what the inferred type costs: whether two months read back together, whether a
field one month lacks is reachable, and what happens to a shape that first appears after
the inference sample.

Run with ``python parquet-compaction-probe.py``; it writes into a temporary directory and
needs only ``duckdb``.
"""

import json
import pathlib
import tempfile

import duckdb

# Three records over two months. Every one is a valid thing the grammar can produce, and
# no two agree on the predicate's shape -- which is the normal case, not a corner one.
MONTHS = {
    "m1": [
        {
            "record_id": "1",
            "outcome": "answered",
            "attempts": [
                {
                    "translation": {"op": "eq", "path": "x", "value": {"literal": 5}},
                    "error": None,
                }
            ],
        },
        {
            "record_id": "2",
            "outcome": "malformed",
            "attempts": [
                {
                    "translation": {
                        "op": "and",
                        "clauses": [
                            {"op": "gt", "path": "y", "value": {"literal": 1}}
                        ],
                    },
                    "error": "no such path",
                }
            ],
        },
    ],
    "m2": [
        {
            "record_id": "3",
            "outcome": "answered",
            "attempts": [
                {
                    "translation": {
                        "op": "exists",
                        "path": "z",
                        "where": {
                            "op": "similarity",
                            "smiles": "c1ccccc1",
                            "threshold": 0.4,
                        },
                    },
                    "error": None,
                }
            ],
        },
    ],
}

# One shape that appears only after a small inference sample, standing in for a predicate
# form that stays rare until the log is large.
LATE = [{"record_id": str(i), "translation": {"op": "eq", "path": "x"}} for i in range(50)]
LATE.append({"record_id": "50", "translation": {"op": "similarity", "threshold": 0.4}})


def write_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    """Writes one JSON object per line."""
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def attempt(connection: duckdb.DuckDBPyConnection, label: str, sql: str) -> None:
    """Runs a query and prints the rows, or the first line of the error."""
    try:
        print(f"   {label:42s} OK      {connection.execute(sql).fetchall()}")
    except Exception as error:  # noqa: BLE001
        print(f"   {label:42s} FAILED  {str(error).splitlines()[0][:110]}")


def main() -> None:
    """Runs the probe."""
    connection = duckdb.connect()
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        for month, records in MONTHS.items():
            write_jsonl(root / f"{month}.json", records)
            inferred = connection.execute(
                f"DESCRIBE SELECT * FROM read_json_auto('{root}/{month}.json')"
            ).fetchall()
            print(
                f"{month} inferred attempts type:\n    "
                + next(column[1] for column in inferred if column[0] == "attempts")
            )
            connection.execute(
                f"COPY (SELECT * FROM read_json_auto('{root}/{month}.json')) "
                f"TO '{root}/{month}.parquet' (FORMAT parquet)"
            )
            connection.execute(
                f"COPY (SELECT record_id, outcome, to_json(attempts) AS attempts "
                f"FROM read_json_auto('{root}/{month}.json')) "
                f"TO '{root}/str_{month}.parquet' (FORMAT parquet)"
            )

        print("\n=== nested: both compacted months together ===")
        attempt(
            connection,
            "count(*)",
            f"SELECT count(*) FROM read_parquet('{root}/m*.parquet')",
        )
        for field in ("clauses", "where"):
            attempt(
                connection,
                f"attempts[1].translation.{field}",
                f"SELECT record_id, attempts[1].translation.{field} FROM "
                f"read_parquet('{root}/m*.parquet') ORDER BY record_id",
            )

        print("\n=== nested: with union_by_name, the documented fix ===")
        for field in ("clauses", "where"):
            attempt(
                connection,
                f"attempts[1].translation.{field}",
                f"SELECT record_id, attempts[1].translation.{field} FROM "
                f"read_parquet('{root}/m*.parquet', union_by_name=true) "
                f"ORDER BY record_id",
            )

        print("\n=== string: the same lookups ===")
        for field in ("clauses", "where"):
            attempt(
                connection,
                f"attempts->'$[0].translation.{field}'",
                f"SELECT record_id, attempts->'$[0].translation.{field}' FROM "
                f"read_parquet('{root}/str_*.parquet') ORDER BY record_id",
            )

        print("\n=== nested: a shape appearing after the inference sample ===")
        write_jsonl(root / "late.json", LATE)
        for sample in (-1, 10):
            inferred = connection.execute(
                f"DESCRIBE SELECT * FROM read_json_auto('{root}/late.json', "
                f"sample_size={sample})"
            ).fetchall()
            print(
                f"   sample_size={sample:<4} -> "
                + next(column[1] for column in inferred if column[0] == "translation")
            )
            attempt(
                connection,
                "translation.threshold (record 50)",
                f"SELECT translation.threshold FROM read_json_auto('{root}/late.json', "
                f"sample_size={sample}) WHERE record_id = '50'",
            )


if __name__ == "__main__":
    main()
