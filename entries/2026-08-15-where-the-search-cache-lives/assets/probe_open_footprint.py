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

"""What does opening a Corpus hold, and how much of it is still in use?

Repeats the steps ``Corpus.__init__`` takes over the projections and structures, one at
a time, and reports three readings after each: resident size, macOS's physical
footprint, and the bytes the default malloc zone still has allocated. Resident size
counts pages malloc has freed and handed back as reusable until the kernel reclaims
them, so on macOS it overstates what the process is using; the other two do not.

Run on macOS from an empty directory, with the corpus under ~/ord/artifacts:

    python probe_open_footprint.py          # parquet_metadata_cache on, as Corpus sets it
    python probe_open_footprint.py --no-cache
"""

import gc
import glob
import os
import re
import subprocess
import sys

import duckdb
import psutil

from ord_schema.search import execute

GIB = 1024**3
ROOT = os.path.expanduser("~/ord/artifacts")


def _vmmap() -> tuple[str, str]:
    """Returns the physical footprint and the default zone's allocated bytes."""
    summary = subprocess.run(  # noqa: S603
        ["/usr/bin/vmmap", "-summary", str(os.getpid())],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    footprint = re.search(r"Physical footprint:\s+(\S+)", summary).group(1)
    zone = next(
        line for line in summary.splitlines() if line.startswith("DefaultMallocZone")
    )
    return footprint, zone.split()[6]


def _report(label: str) -> None:
    gc.collect()
    resident = psutil.Process().memory_info().rss / GIB
    footprint, allocated = _vmmap()
    print(
        f"{label:40s} resident {resident:5.2f} GiB  footprint {footprint:>6s}  "
        f"allocated {allocated:>6s}",
        flush=True,
    )


def main() -> None:
    cache = "--no-cache" not in sys.argv
    _report("imports")
    pairs, _ = execute._pair(
        f"{ROOT}/projections/**/*.parquet", f"{ROOT}/structures/**/*.parquet", True
    )
    _report(f"_pair ({len(pairs)} pairs)")
    for projected, _, _, _ in pairs:
        execute._max_structure_id(projected, "")
    _report("_max_structure_id over every projection")
    connection = duckdb.connect()
    if cache:
        execute._cache_footers(connection)
    structures = execute._sql_paths(pair[1] for pair in pairs)
    connection.execute(f"SELECT count(*) FROM read_parquet({structures})").fetchone()
    _report("DuckDB counts the structures")
    projections = execute._sql_paths(pair[0] for pair in pairs)
    connection.execute(f"SELECT count(*) FROM read_parquet({projections})").fetchone()
    _report(f"DuckDB counts the projections (cache {'on' if cache else 'off'})")
    for tag, held in connection.execute(
        "SELECT tag, memory_usage_bytes FROM duckdb_memory() "
        "WHERE memory_usage_bytes > 0 ORDER BY 2 DESC"
    ).fetchall():
        print(f"    duckdb_memory {tag:24s} {held / GIB:5.2f} GiB")
    footers = groups = 0
    for projected, _, _, _ in pairs:
        metadata = execute.pq.ParquetFile(projected).metadata
        footers += metadata.serialized_size
        groups += metadata.num_row_groups
    print(
        f"    projection footers: {len(pairs)} files, {groups} row groups x "
        f"{metadata.num_columns} columns, {footers / 1024**2:.0f} MiB serialized"
    )


if __name__ == "__main__":
    main()
