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

"""How close does building the occurrence index bring a capped container to its cap?

``probe_container_index.py`` (finding 19) run against the Corpus of ord-schema 0.9.5:
two-column occurrences, ``warm=False`` so ``check_index`` builds the index and nothing
else, and the index unnested from the projections, with no pivots_dir and no
occurrences_dir. Finding 20.

A kill leaves exit 137 and no closing line, so the sampler prints the running peak every
five seconds; the last ``peak`` line before a kill is how far the process got.
``--memory-swap`` equal to ``--memory`` turns swap off, as a deployment has it. Docker's
default lets a container swap as much again, and a run that swaps reports a lower
resident peak and takes far longer to be killed.

    docker run --name probe --memory=8g --memory-swap=8g -w /spill \\
        -v "$PWD":/probe:ro -v /path/to/ord-schema:/repo:ro \\
        -v ~/ord/artifacts:/artifacts:ro -v probe-spill:/spill \\
        -e PYTHONPATH=/repo -e PYTHONUNBUFFERED=1 \\
        ord-probe python /probe/probe_container_rebuild.py
    docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' probe

``ord-probe`` is python:3.14-slim with ord-schema's requirements at the versions its
uv.lock pins (DuckDB 1.5.5, RDKit 2026.03.5, pyarrow 24.0.0) and psutil. Set
DUCKDB_MEMORY_LIMIT to hold DuckDB below what it would claim for itself, and
PROBE_OPEN_ONLY=1 to report the open and stop.
"""

import json
import os
import pathlib
import shutil
import threading
import time

import duckdb

from ord_schema.search import execute

GIB = 1024**3
CGROUP = pathlib.Path("/sys/fs/cgroup")


def _status_kib(field: str) -> int:
    """Returns a /proc/self/status field in KiB."""
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    raise KeyError(field)


def _cgroup_int(name: str) -> int | None:
    path = CGROUP / name
    return int(path.read_text()) if path.exists() else None


def _cgroup_stat() -> dict[str, int]:
    stat = {}
    for line in (CGROUP / "memory.stat").read_text().splitlines():
        key, value = line.split()
        stat[key] = int(value)
    return stat


def _directory_bytes(path: str) -> int:
    total = 0
    for root, _, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _gib(value: int | None) -> float | None:
    return None if value is None else round(value / GIB, 3)


class _Sampler(threading.Thread):
    """Tracks peak RSS, peak cgroup anon, and peak spill, printing them as it goes."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stopped = threading.Event()
        self.peak_rss = 0
        self.peak_anon = 0
        self.peak_spill = 0
        self.started = time.perf_counter()

    def run(self) -> None:
        last = 0.0
        while not self.stopped.is_set():
            self.peak_rss = max(self.peak_rss, _status_kib("VmRSS") * 1024)
            self.peak_anon = max(self.peak_anon, _cgroup_stat()["anon"])
            self.peak_spill = max(self.peak_spill, _directory_bytes(".tmp"))
            now = time.perf_counter() - self.started
            if now - last >= 5:
                last = now
                print(
                    f"peak t={now:5.0f}s rss {self.peak_rss / GIB:.2f} GiB "
                    f"anon {self.peak_anon / GIB:.2f} GiB "
                    f"cgroup {(_cgroup_int('memory.current') or 0) / GIB:.2f} GiB "
                    f"spill {self.peak_spill / GIB:.1f} GiB",
                    flush=True,
                )
            time.sleep(0.1)


def main() -> None:
    result: dict[str, object] = {
        "memory_max": (CGROUP / "memory.max").read_text().strip(),
        "requested_limit": os.environ.get("DUCKDB_MEMORY_LIMIT"),
        "rss_interpreter_gib": _gib(_status_kib("VmRSS") * 1024),
    }
    print(json.dumps(result), flush=True)
    opened = time.perf_counter()
    corpus = execute.Corpus(
        "/artifacts/projections/**/*.parquet",
        "/artifacts/structures/**/*.parquet",
        resolver={}.__getitem__,
        pivot_budget_bytes=0,
        memory_limit=os.environ.get("DUCKDB_MEMORY_LIMIT"),
        warm=False,
    )
    result["open_s"] = round(time.perf_counter() - opened, 1)
    connection = corpus._connection
    result["duckdb_memory_limit"] = connection.execute(
        "SELECT current_setting('memory_limit')"
    ).fetchone()[0]
    result["duckdb_threads"] = connection.execute(
        "SELECT current_setting('threads')"
    ).fetchone()[0]
    result["rss_open_gib"] = _gib(_status_kib("VmRSS") * 1024)
    result["cgroup_open_gib"] = _gib(_cgroup_int("memory.current"))
    result["anon_open_gib"] = _gib(_cgroup_stat()["anon"])
    result["duckdb_open"] = {
        tag: _gib(value)
        for tag, value in connection.execute(
            "SELECT tag, memory_usage_bytes FROM duckdb_memory() "
            "WHERE memory_usage_bytes > 0"
        ).fetchall()
    }
    print(json.dumps(result), flush=True)
    if os.environ.get("PROBE_OPEN_ONLY"):
        return

    sampler = _Sampler()
    sampler.start()
    start = time.perf_counter()
    try:
        counts = corpus.check_index()
    except duckdb.Error as error:
        result["outcome"] = f"{type(error).__name__} after {time.perf_counter() - start:.0f}s"
        result["error"] = str(error).splitlines()[0]
    else:
        result["outcome"] = f"built in {time.perf_counter() - start:.0f}s"
        result["rows"] = sum(counts.values())
        result["table_gib"] = _gib(execute._memory_bytes(connection))
    sampler.stopped.set()
    sampler.join()
    result["peak_rss_gib"] = _gib(max(sampler.peak_rss, _status_kib("VmHWM") * 1024))
    result["peak_anon_gib"] = _gib(sampler.peak_anon)
    result["cgroup_peak_gib"] = _gib(_cgroup_int("memory.peak"))
    result["peak_spill_gib"] = _gib(sampler.peak_spill)
    print(json.dumps(result), flush=True)
    corpus.close()
    shutil.rmtree(".tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
