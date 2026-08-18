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

"""Does DuckDB size its defaults from the container's cap or from the host?

Which one it reads decides how a constrained deployment fails: from the cgroup, it
raises OutOfMemoryException that a caller can catch and a startup check can surface;
from the host, it allocates past the cap and the kernel ends the process.

Prints the cap, what /proc/meminfo advertises, and the settings DuckDB arrives at, then
asks for more memory than the cap allows with nowhere to spill, to see which way the
refusal comes back. Run it under a cap, with a CPU quota to see `threads` follow:

    docker run --rm --memory=2g --cpus=2 -v "$PWD":/probe:ro python:3.11-slim \\
        bash -c 'pip install -q duckdb && python /probe/probe_cgroup.py'
"""

import pathlib

import duckdb


def read(path: str) -> str:
    """Returns the contents of ``path``, stripped."""
    return pathlib.Path(path).read_text().strip()


def main() -> None:
    print("cgroup memory.max  :", read("/sys/fs/cgroup/memory.max"))
    print("cgroup cpu.max     :", read("/sys/fs/cgroup/cpu.max"))
    total = next(
        line for line in read("/proc/meminfo").splitlines() if line.startswith("MemTotal")
    )
    print("/proc/meminfo      :", total.split(":")[1].strip())

    connection = duckdb.connect()
    for setting in ("memory_limit", "threads"):
        value = connection.execute(f"SELECT current_setting('{setting}')").fetchone()[0]
        print(f"duckdb {setting:<12}:", value)

    # A sort over more rows than the cap holds, with spilling turned off so the only way
    # through it is to keep the whole thing in memory.
    connection.execute("SET temp_directory = ''")
    print("\nsorting 6 GB with no spill directory:")
    try:
        connection.execute(
            "SELECT i, repeat('x', 200) AS pad FROM range(30000000) t(i) ORDER BY pad, i"
        ).fetchone()
        print("  finished, so the memory was there")
    except duckdb.Error as error:
        print(f"  {type(error).__name__}: {str(error).splitlines()[0]}")


if __name__ == "__main__":
    main()
