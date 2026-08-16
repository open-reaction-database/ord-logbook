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

"""How much memory does the occurrence index build actually need, and why?

Two hypotheses failed: stopping insertion-order preservation, and giving DuckDB a
temp_directory to spill into. Neither helped, so the next thing to establish is what the
allocator is actually complaining about and where the threshold sits.

Prints the whole error rather than its type, and confirms the settings took effect
instead of assuming they did.
"""

import logging
import os
import subprocess
import sys
import tempfile
import time

import psutil

from ord_schema.search import execute

HOME = os.path.expanduser("~")
LIMITS = ("4GB", "5GB", "6GB", "8GB")


def _measure(limit: str) -> None:
    """Builds the index once at one limit, reporting what happened in full."""
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
        settings = corpus._connection.execute(
            "SELECT current_setting('memory_limit'), current_setting('temp_directory'), "
            "current_setting('threads')"
        ).fetchone()
        print(f"[{limit}] settings in force: {settings}")
        start = time.perf_counter()
        try:
            corpus._occurrences()
        except Exception as error:  # noqa: BLE001
            print(f"[{limit}] FAILED after {time.perf_counter() - start:.0f}s: {error}")
            return
        spent = time.perf_counter() - start
        rows = corpus._connection.execute(
            "SELECT count(*) FROM occurrences"
        ).fetchone()[0]
        spilled = sum(
            os.path.getsize(os.path.join(root, name))
            for root, _, names in os.walk(scratch)
            for name in names
        )
        print(
            f"[{limit}] built {rows:,} rows in {spent:.0f}s, "
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
