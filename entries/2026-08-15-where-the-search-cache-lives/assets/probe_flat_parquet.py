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

"""Times the pivoted tables read from Parquet, cold and warm, across memory limits.

Exports the pivoted tables to Parquet, then times each query on a fresh connection and
on repeats, at several memory limits.

The hypothesis this was built to test -- that flat data would show a memory-sensitivity
curve where the nested native file showed none -- is not one it can answer. The Parquet
has just been written, so a fresh connection still reads through the OS page cache, and
at 381 MiB the dataset fits inside the smallest limit tested, so nothing is ever
evicted. What it does measure is the cost of reading pivoted Parquet at all, which is
about 3x the in-memory form and small in absolute terms.
"""

import pathlib
import time

import duckdb

FLAT = pathlib.Path("/tmp/ord_flat.duckdb")  # noqa: S108 - a scratch measurement.
PARQUET = pathlib.Path("/tmp/ord_flat_parquet")  # noqa: S108 - a scratch measurement.
TABLES = ("reaction", "measurement", "product")

QUERIES = {
    "yield > 50%": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT reaction_id FROM measurement
            WHERE type = 'YIELD' AND percentage_value > 50
        )
    """,
    "a white product": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT reaction_id FROM product WHERE isolated_color = 'white'
        )
    """,
    "above 350 K": "SELECT count(*) FROM reaction WHERE temperature_kelvin > 350",
    "desired product, yield > 50%": """
        SELECT count(*) FROM reaction WHERE reaction_id IN (
            SELECT m.reaction_id FROM measurement AS m
            JOIN product AS p
              ON p.reaction_id = m.reaction_id
             AND p.outcome_index = m.outcome_index
            WHERE m.type = 'YIELD' AND m.percentage_value > 50
              AND p.is_desired_product
        )
    """,
}


def _export() -> None:
    if PARQUET.exists():
        size = sum(path.stat().st_size for path in PARQUET.glob("*.parquet"))
        print(f"reusing {PARQUET} ({size / 1024**2:.0f} MB)\n", flush=True)
        return
    PARQUET.mkdir(parents=True)
    connection = duckdb.connect(str(FLAT), read_only=True)
    try:
        for name in TABLES:
            target = PARQUET / f"{name}.parquet"
            # ZSTD and a sort on the predicate columns: what an artifact would ship, so
            # row-group statistics can skip whole groups rather than only decompress
            # them faster.
            order = {
                "measurement": "ORDER BY type, percentage_value",
                "product": "ORDER BY isolated_color",
                "reaction": "ORDER BY temperature_kelvin",
            }[name]
            connection.execute(
                f"COPY (SELECT * FROM {name} {order}) TO '{target}' "
                "(FORMAT parquet, COMPRESSION zstd)"
            )
            print(
                f"  wrote {name:12s} {target.stat().st_size / 1024**2:7.1f} MB",
                flush=True,
            )
    finally:
        connection.close()
    size = sum(path.stat().st_size for path in PARQUET.glob("*.parquet"))
    print(f"  total {size / 1024**2:.0f} MB\n", flush=True)


def _views(connection: duckdb.DuckDBPyConnection) -> None:
    for name in TABLES:
        connection.execute(
            f"CREATE VIEW {name} AS SELECT * FROM "
            f"read_parquet('{PARQUET / f'{name}.parquet'}')"
        )


def main() -> None:
    _export()
    print(f"{'query':32s} {'limit':>6s} {'cold':>8s} {'warm':>8s}")
    for limit in ("1GB", "4GB", "8GB"):
        for label, sql in QUERIES.items():
            # A fresh connection is the only way to get a genuinely cold cache: the
            # external file cache lives in the database instance.
            connection = duckdb.connect()
            connection.execute(f"SET memory_limit='{limit}'")
            connection.execute("SET parquet_metadata_cache=true")
            _views(connection)
            start = time.perf_counter()
            count = connection.execute(sql).fetchone()[0]
            cold = time.perf_counter() - start
            warm = None
            for _ in range(3):
                start = time.perf_counter()
                connection.execute(sql)
                spent = time.perf_counter() - start
                warm = spent if warm is None else min(warm, spent)
            print(
                f"{label:32s} {limit:>6s} {cold:7.3f}s {warm:7.3f}s  ({count:,})",
                flush=True,
            )
            connection.close()
        print(flush=True)


if __name__ == "__main__":
    main()
