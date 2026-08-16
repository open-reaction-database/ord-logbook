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

"""What does chunking cost on a machine that is not short of memory?

Chunking per projection file drops the build's floor from about 5 GB to about 2 GB, and
the question that decides whether it should simply be the build is what it costs where
nothing is constrained -- which is the configuration most deployments run, and the one
where the single statement takes 57s and spills nothing.

No memory_limit is set, so DuckDB takes its default share of the machine, exactly as a
Corpus does today.
"""

import logging
import os
import subprocess
import sys
import tempfile
import time

import psutil

from ord_schema.search import execute
from ord_schema.search import query as query_module

HOME = os.path.expanduser("~")
SHAPES = ("whole", "chunked")


def _measure(shape: str) -> None:
    """Builds the index one way at DuckDB's default limit."""
    logging.disable(logging.INFO)
    process = psutil.Process()
    with (
        tempfile.TemporaryDirectory() as scratch,
        execute.Corpus(
            f"{HOME}/ord/projections/**/*.parquet",
            f"{HOME}/ord/structures/**/*.parquet",
            resolver={}.__getitem__,
            require_current=False,
            narrow_budget_bytes=0,
        ) as corpus,
    ):
        corpus._connection.execute(f"SET GLOBAL temp_directory='{scratch}'")
        limit = corpus._connection.execute(
            "SELECT current_setting('memory_limit')"
        ).fetchone()[0]
        cursor = corpus._connection.cursor()
        start = time.perf_counter()
        if shape == "whole":
            corpus._occurrences()
        else:
            offsets = cursor.execute(
                "SELECT projection_filename, structure_offset FROM structure_offsets "
                "ORDER BY structure_offset"
            ).fetchall()
            created = False
            for filename, offset in offsets:
                escaped = filename.replace("'", "''")
                for path, expression in execute.INDEXED_PATHS.items():
                    select = f"""
                        SELECT reaction_id, '{path}' AS path,
                               (element.structure_id + {offset})::UINTEGER AS global_id,
                               element.reaction_role AS reaction_role
                        FROM read_parquet('{escaped}'),
                             unnest({expression}) AS unnested(element)
                        WHERE element.structure_id IS NOT NULL
                    """
                    if created:
                        cursor.execute(f"INSERT INTO occurrences {select}")
                    else:
                        cursor.execute(
                            f"CREATE OR REPLACE TABLE occurrences AS {select}"
                        )
                        created = True
        spent = time.perf_counter() - start
        rows, reached = cursor.execute(
            "SELECT count(*), count(DISTINCT global_id) FROM occurrences"
        ).fetchone()
        held = cursor.execute(
            "SELECT coalesce(sum(memory_usage_bytes), 0) FROM duckdb_memory() "
            "WHERE tag = 'IN_MEMORY_TABLE'"
        ).fetchone()[0]
        spilled = sum(
            os.path.getsize(os.path.join(root, name))
            for root, _, names in os.walk(scratch)
            for name in names
        )
        cursor.close()
        print(
            f"[{shape}, limit {limit}] {rows:,} rows reaching {reached:,} structures "
            f"in {spent:.0f}s, table {held / 1024**3:.2f} GiB, "
            f"process {process.memory_info().rss / 1024**3:.2f} GiB, "
            f"{spilled / 1024**3:.2f} GiB spilled"
        )


def main() -> None:
    for shape in SHAPES:
        subprocess.run([sys.executable, "-u", __file__, shape], check=False)  # noqa: S603


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
