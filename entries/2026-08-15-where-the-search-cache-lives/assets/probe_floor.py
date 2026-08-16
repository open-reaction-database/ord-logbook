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

"""What does a server hold before it answers anything, and how much of it is elective?

Reported as process resident size rather than as the size of any one object: a container
is sized against the process, and how much of a growth is an object and how much is
allocator slack is not a distinction a memory limit makes.

DuckDB's ``memory_limit`` defaults to a fraction of the machine and its caches fill what
they are given, so the same sequence is run at two limits. What moves between them is
elective; what does not is the floor.
"""

import gc
import logging
import os
import subprocess
import sys
import time

import psutil

from ord_schema.search import execute

HOME = os.path.expanduser("~")
LIMITS = ("2GB", "6GB", "16GB")


def _resident(process: psutil.Process) -> float:
    """Returns this process's resident size in GiB, after collecting garbage."""
    gc.collect()
    return process.memory_info().rss / 1024**3


def _measure(limit: str) -> None:
    """Opens a corpus at one DuckDB memory limit and reports each step's residency."""
    logging.disable(logging.INFO)
    process = psutil.Process()
    steps = [("interpreter", _resident(process))]
    with execute.Corpus(
        f"{HOME}/ord/projections/**/*.parquet",
        f"{HOME}/ord/structures/**/*.parquet",
        resolver={}.__getitem__,
        require_current=False,
        narrow_budget_bytes=0,
        pivots_dir=f"{HOME}/ord/pivots",
    ) as corpus:
        corpus._connection.execute(f"SET GLOBAL memory_limit='{limit}'")
        steps.append(("corpus open", _resident(process)))
        corpus.check_pivots()
        steps.append(("pivots published", _resident(process)))
        start = time.perf_counter()
        corpus._library()
        library = time.perf_counter() - start
        steps.append(("library built", _resident(process)))
        start = time.perf_counter()
        corpus._occurrences()
        index = time.perf_counter() - start
        steps.append(("index built", _resident(process)))
        held = corpus._connection.execute(
            "SELECT tag, sum(memory_usage_bytes) FROM duckdb_memory() "
            "WHERE memory_usage_bytes > 0 GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    print(f"\n=== memory_limit {limit} (library {library:.0f}s, index {index:.0f}s)")
    for label, resident in steps:
        print(f"    {label:20s} {resident:6.2f} GiB")
    for tag, value in held:
        print(f"    duckdb {tag:38s} {value / 1024**3:6.2f} GiB")


def main() -> None:
    for limit in LIMITS:
        subprocess.run(  # noqa: S603
            [sys.executable, "-u", __file__, limit], check=False
        )


if __name__ == "__main__":
    if len(sys.argv) == 2:
        _measure(sys.argv[1])
    else:
        main()
