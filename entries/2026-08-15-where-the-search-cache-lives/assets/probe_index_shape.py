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

"""Does the occurrence index have to be built as one statement?

The build is a single ``CREATE TABLE ... AS`` over a ``UNION ALL`` of one SELECT per
indexed path. At a 4 GB DuckDB limit it fails to pin a block; at 5 GB it succeeds but
spills 16 GB to disk for a table whose result is 1.19 GiB. Both are consequences of how
much of the work is in flight at once.

Building the same rows path by path -- CREATE from the first, INSERT the rest -- puts one
path in flight instead of five. Same rows either way, which is checked rather than
assumed.
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
CASES = (("2GB", "union"), ("2GB", "per-path"), ("4GB", "per-path"), ("1GB", "per-path"))


def _selects() -> dict[str, str]:
    """Returns one SELECT per indexed path, as the shipped build assembles them."""
    return {
        path: f"""
        SELECT reaction_id, '{path}' AS path,
               (element.structure_id + {query_module.STRUCTURE_OFFSET})::UINTEGER
                   AS global_id,
               element.reaction_role AS reaction_role
        FROM {query_module.TABLE}, unnest({expression}) AS unnested(element)
        WHERE element.structure_id IS NOT NULL
        """
        for path, expression in execute.INDEXED_PATHS.items()
    }


def _measure(limit: str, shape: str) -> None:
    """Builds the index one way at one limit and reports what it cost."""
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
        corpus._connection.execute(f"SET GLOBAL memory_limit='{limit}'")
        corpus._connection.execute(f"SET GLOBAL temp_directory='{scratch}'")
        selects = _selects()
        cursor = corpus._connection.cursor()
        start = time.perf_counter()
        try:
            if shape == "union":
                cursor.execute(
                    "CREATE OR REPLACE TABLE occurrences AS "
                    + "\nUNION ALL\n".join(selects.values())
                )
            else:
                for index, select in enumerate(selects.values()):
                    if index == 0:
                        cursor.execute(
                            f"CREATE OR REPLACE TABLE occurrences AS {select}"
                        )
                    else:
                        cursor.execute(f"INSERT INTO occurrences {select}")
        except Exception as error:  # noqa: BLE001
            print(
                f"[{limit} {shape}] FAILED after {time.perf_counter() - start:.0f}s: "
                f"{str(error).splitlines()[0]}"
            )
            return
        spent = time.perf_counter() - start
        rows = cursor.execute("SELECT count(*) FROM occurrences").fetchone()[0]
        spilled = sum(
            os.path.getsize(os.path.join(root, name))
            for root, _, names in os.walk(scratch)
            for name in names
        )
        cursor.close()
        print(
            f"[{limit} {shape}] {rows:,} rows in {spent:.0f}s, "
            f"process {process.memory_info().rss / 1024**3:.2f} GiB, "
            f"{spilled / 1024**3:.2f} GiB spilled"
        )


def main() -> None:
    for limit, shape in CASES:
        subprocess.run([sys.executable, "-u", __file__, limit, shape], check=False)  # noqa: S603


if __name__ == "__main__":
    if len(sys.argv) == 3:
        _measure(sys.argv[1], sys.argv[2])
    else:
        main()
