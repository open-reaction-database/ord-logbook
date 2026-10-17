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

"""Where does a Corpus open's memory go in a Linux container, and is any of it free?

``probe_open_footprint.py`` run in the container instead of on the laptop: the steps
``Corpus.__init__`` takes over the projections and structures, one at a time, with
resident size, the cgroup's anonymous memory, and glibc's own split of its heap into
bytes in use and bytes freed but kept. Freed-but-kept is what the laptop's resident size
could not tell apart from a real allocation. Finding 20.

The structure_id bound is read three ways, named by the argument:

* ``schema``: through ``metadata.schema``, as ord-schema 0.9.5 did. pyarrow's
  ``ParquetSchema`` and its ``FileMetaData`` refer to each other, so every footer waits
  for the cyclic collector.
* ``chunks``: from the first row group's chunk paths, which form no cycle, as
  ord-schema#1127 does.
* ``duckdb``: through DuckDB's ``parquet_metadata()``, which parses into the same
  cache the reactions count fills.

Run it like probe_container_rebuild.py, with the variant as the argument:

    docker run --rm --memory=12g --memory-swap=12g -v "$PWD":/probe:ro \\
        -v /path/to/ord-schema:/repo:ro -v ~/ord/artifacts:/artifacts:ro \\
        -e PYTHONPATH=/repo ord-probe python /probe/probe_open_steps_container.py chunks
"""

import ctypes
import gc
import json
import pathlib
import sys

import duckdb
import pyarrow.parquet as pq

from ord_schema.search import execute

GIB = 1024**3


class _Mallinfo2(ctypes.Structure):
    _fields_ = [  # noqa: RUF012
        (name, ctypes.c_size_t)
        for name in (
            "arena",
            "ordblks",
            "smblks",
            "hblks",
            "hblkhd",
            "usmblks",
            "fsmblks",
            "uordblks",
            "fordblks",
            "keepcost",
        )
    ]


_LIBC = ctypes.CDLL("libc.so.6")
_LIBC.mallinfo2.restype = _Mallinfo2


def _resident() -> float:
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024 / GIB
    raise KeyError("VmRSS")


def _anonymous() -> float:
    for line in pathlib.Path("/sys/fs/cgroup/memory.stat").read_text().splitlines():
        key, value = line.split()
        if key == "anon":
            return int(value) / GIB
    raise KeyError("anon")


def _report(label: str) -> None:
    gc.collect()
    heap = _LIBC.mallinfo2()
    print(
        f"{label:36s} resident {_resident():5.2f}  anon {_anonymous():5.2f}  "
        f"glibc in use {(heap.uordblks + heap.hblkhd) / GIB:5.2f}  "
        f"freed and kept {heap.fordblks / GIB:5.2f} GiB",
        flush=True,
    )


def _bound_from_chunks(path: str) -> int | None:
    """The structure_id bound, finding the columns by their chunks' paths."""
    with pq.ParquetFile(path) as parquet_file:
        metadata = parquet_file.metadata
        columns: list[int] = []
        largest = None
        for group in range(metadata.num_row_groups):
            row_group = metadata.row_group(group)
            if group == 0:
                columns = [
                    index
                    for index in range(row_group.num_columns)
                    if row_group.column(index).path_in_schema.rsplit(".", 1)[-1]
                    == "structure_id"
                ]
            for index in columns:
                statistics = row_group.column(index).statistics
                if statistics is not None and statistics.has_min_max:
                    value = statistics.max
                    largest = value if largest is None else max(largest, value)
    return largest


def main() -> None:
    variant = sys.argv[1]
    _report("imports")
    pairs, _ = execute._pair(
        "/artifacts/projections/**/*.parquet", "/artifacts/structures/**/*.parquet", True
    )
    _report(f"_pair ({len(pairs)} pairs)")
    for projected, structured, _, _ in pairs:
        with pq.ParquetFile(structured) as artifact:
            _ = artifact.metadata.num_rows
        with pq.ParquetFile(projected) as artifact:
            _ = artifact.metadata.num_rows
    _report("row counts of both sides")
    connection = duckdb.connect()
    execute._cache_footers(connection)
    projections = execute._sql_paths(pair[0] for pair in pairs)
    if variant == "schema":
        for projected, _, _, _ in pairs:
            with pq.ParquetFile(projected) as parquet_file:
                metadata = parquet_file.metadata
                _ = [
                    index
                    for index in range(metadata.num_columns)
                    if metadata.schema.column(index).name == "structure_id"
                ]
    elif variant == "chunks":
        for projected, _, _, _ in pairs:
            _bound_from_chunks(projected)
    elif variant == "duckdb":
        connection.execute(
            "SELECT file_name, max(coalesce(stats_max_value, stats_max)::BIGINT) "  # noqa: S608
            f"FROM parquet_metadata({projections}) "
            "WHERE path_in_schema = 'structure_id' "
            "OR ends_with(path_in_schema, ', structure_id') GROUP BY file_name"
        ).fetchall()
    else:
        raise SystemExit(f"unknown variant {variant}; pass schema, chunks, or duckdb")
    _report(f"structure_id bound ({variant})")
    structures = execute._sql_paths(pair[1] for pair in pairs)
    connection.execute(
        f"SELECT count(*), count(pattern_fp) FROM read_parquet({structures})"  # noqa: S608
    ).fetchone()
    _report("DuckDB counts the structures")
    connection.execute(f"SELECT count(*) FROM read_parquet({projections})").fetchone()  # noqa: S608
    _report("DuckDB counts the projections")
    print(
        json.dumps(
            {
                tag: round(held / GIB, 3)
                for tag, held in connection.execute(
                    "SELECT tag, memory_usage_bytes FROM duckdb_memory() "
                    "WHERE memory_usage_bytes > 0"
                ).fetchall()
            }
        )
    )


if __name__ == "__main__":
    main()
