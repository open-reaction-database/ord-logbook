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

"""How does a container too small for the occurrence index find out?

Builds the index under a memory cap and reports which way it ends: an
OutOfMemoryException the caller can catch, or a kill the process never sees. Read the
verdict from outside -- an exception exits 0 and prints, a kill leaves exit 137 and no
output at all:

    docker run --name probe --memory=8g -w /spill \\
        -v "$PWD":/probe:ro -v /path/to/ord-schema:/repo:ro \\
        -v ~/ord/projections:/projections:ro -v ~/ord/structures:/structures:ro \\
        -v /var/tmp/spill:/spill -e PYTHONPATH=/repo -e PYTHONUNBUFFERED=1 \\
        ord-probe python /probe/probe_container_index.py
    docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' probe

Set DUCKDB_MEMORY_LIMIT to hold DuckDB below what it would claim for itself, which is
about 80% of the cap. Give /spill a volume rather than a bind mount: the build writes 16
to 25 GB of temporary files, and removing them again through a bind mount takes longer
than the build does.
"""

import os
import pathlib
import resource
import time

import duckdb

from ord_schema.search import execute


def resident_mib() -> float:
    """Returns this process's peak resident size in MiB, as Linux reports it."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:
    print("cgroup memory.max  :", pathlib.Path("/sys/fs/cgroup/memory.max").read_text())
    requested = os.environ.get("DUCKDB_MEMORY_LIMIT")
    corpus = execute.Corpus(
        "/projections/**/*.parquet",
        "/structures/**/*.parquet",
        require_current=False,
        pivot_budget_bytes=0,
        memory_limit=requested,
    )
    limit = corpus._connection.execute(
        "SELECT current_setting('memory_limit')"
    ).fetchone()[0]
    print(f"duckdb memory_limit: {limit}")
    print(f"resident after open: {resident_mib():.0f} MiB")

    start = time.perf_counter()
    try:
        counts = corpus.check_index()
    except duckdb.Error as error:
        elapsed = time.perf_counter() - start
        print(f"\ncheck_index raised {type(error).__name__} after {elapsed:.0f}s")
        print(f"  {str(error).splitlines()[0]}")
    else:
        elapsed = time.perf_counter() - start
        print(f"\ncheck_index finished in {elapsed:.0f}s: {sum(counts.values())} found")
    print(f"peak resident      : {resident_mib():.0f} MiB")


if __name__ == "__main__":
    main()
