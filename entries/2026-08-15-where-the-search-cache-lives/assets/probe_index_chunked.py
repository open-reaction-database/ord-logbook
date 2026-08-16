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

"""Does chunking the index build by projection file lower its memory floor?

The floor is not the shape of the statement -- one UNION ALL and five separate INSERTs
fail alike. Both put the *whole corpus* through one unnest, so the remaining lever is to
put one file through it at a time: 53 projections times five indexed paths, each
statement bounded by a single file rather than by 2.4M reactions.

Each projection's structure IDs are corpus-wide only after its own offset is added, and
the offset is per file, so chunking by file is also the granularity the offset already
has.
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
LIMITS = ("1GB", "2GB", "4GB")


def _measure(limit: str) -> None:
    """Builds the index a file at a time at one limit and reports what it cost."""
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
        cursor = corpus._connection.cursor()
        offsets = cursor.execute(
            "SELECT projection_filename, structure_offset FROM structure_offsets "
            "ORDER BY structure_offset"
        ).fetchall()
        start = time.perf_counter()
        created = False
        try:
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
        except Exception as error:  # noqa: BLE001
            print(
                f"[{limit}] FAILED after {time.perf_counter() - start:.0f}s: "
                f"{str(error).splitlines()[0]}"
            )
            return
        spent = time.perf_counter() - start
        rows = cursor.execute("SELECT count(*) FROM occurrences").fetchone()[0]
        reached = cursor.execute(
            "SELECT count(DISTINCT global_id) FROM occurrences"
        ).fetchone()[0]
        spilled = sum(
            os.path.getsize(os.path.join(root, name))
            for root, _, names in os.walk(scratch)
            for name in names
        )
        cursor.close()
        print(
            f"[{limit}] {rows:,} rows reaching {reached:,} structures in {spent:.0f}s, "
            f"process {process.memory_info().rss / 1024**3:.2f} GiB, "
            f"{spilled / 1024**3:.2f} GiB spilled"
        )


def main() -> None:
    for limit in LIMITS:
        subprocess.run([sys.executable, "-u", __file__, limit], check=False)  # noqa: S603


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
