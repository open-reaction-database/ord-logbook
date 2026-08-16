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

"""Does a query pay for the struct fields it does not name?

A pivot's ``element`` is one struct column holding every field the level's element
carries, so a wide level makes a wide struct. Whether that costs a query anything
decides whether pruning the element further is worth doing: if a scan reads only the
fields the predicate names, a wide pivot costs disk and nothing else.

Parquet stores a struct's fields as separate columns, so the answer should be no. Asked
rather than assumed, over data that cannot compress away -- repeated strings compress to
nothing under zstd, and a file that small would answer every question in the same
millisecond.
"""

import pathlib
import time

import duckdb

OUTPUT = pathlib.Path("/tmp/ord_structpush")  # noqa: S108
ROWS = 3_000_000

QUERIES = {
    "narrow field only": "element.a > 100",
    "one wide field": "element.b LIKE 'q%'",
    "three wide fields": (
        "element.b LIKE 'q%' AND element.c LIKE 'q%' AND element.d LIKE 'q%'"
    ),
    "whole struct": "element IS NOT NULL",
}

RUNS = 3


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / "wide.parquet"
    connection = duckdb.connect()
    connection.execute("SET parquet_metadata_cache=true")
    if not path.exists():
        connection.execute(f"""
            COPY (
                SELECT i AS reaction_id,
                       {{'a': i,
                         'b': md5(i::VARCHAR) || md5((i + 1)::VARCHAR),
                         'c': md5((i + 2)::VARCHAR) || md5((i + 3)::VARCHAR),
                         'd': md5((i + 4)::VARCHAR) || md5((i + 5)::VARCHAR)}} AS element
                FROM range({ROWS}) t(i)
            ) TO '{path}' (FORMAT parquet, COMPRESSION zstd)
        """)
    print(f"{path.stat().st_size / 1024**2:.0f} MiB, {ROWS:,} rows\n")
    for label, predicate in QUERIES.items():
        # S608: the predicates are this module's own constants.
        sql = (
            f"SELECT count(*) FROM read_parquet('{path}') WHERE {predicate}"  # noqa: S608
        )
        spent = None
        for _ in range(RUNS):
            start = time.perf_counter()
            connection.execute(sql).fetchall()
            spent = time.perf_counter() - start
        print(f"{label:20s} {spent:.3f}s")
    connection.close()


if __name__ == "__main__":
    main()
