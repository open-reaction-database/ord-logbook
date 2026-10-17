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

"""What a warmed corpus holds in a container: the figure a deployment is sized against.

Opens Corpus(warm=True), which builds the occurrence index and then the substructure
library, and reports resident size after each and the peak across the open. The index
comes from pivot artifacts (PROBE_ROUTE=pivots) or is a view over occurrence artifacts
(PROBE_ROUTE=view). Finding 20. Run it like probe_container_rebuild.py, adding
``-e PROBE_ROUTE=pivots`` or ``-e PROBE_ROUTE=view``.
"""

import json
import os
import pathlib
import threading
import time

from ord_schema.search import execute

GIB = 1024**3
CGROUP = pathlib.Path("/sys/fs/cgroup")


def _status_kib(field: str) -> int:
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    raise KeyError(field)


def _anon() -> int:
    for line in (CGROUP / "memory.stat").read_text().splitlines():
        key, value = line.split()
        if key == "anon":
            return int(value)
    raise KeyError("anon")


def _gib(value: float) -> float:
    return round(value / GIB, 3)


class _Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stopped = threading.Event()
        self.peak_rss = 0
        self.peak_anon = 0

    def run(self) -> None:
        while not self.stopped.is_set():
            self.peak_rss = max(self.peak_rss, _status_kib("VmRSS") * 1024)
            self.peak_anon = max(self.peak_anon, _anon())
            time.sleep(0.1)


def main() -> None:
    route = os.environ["PROBE_ROUTE"]
    result: dict[str, object] = {
        "route": route,
        "memory_max": (CGROUP / "memory.max").read_text().strip(),
        "requested_limit": os.environ.get("DUCKDB_MEMORY_LIMIT"),
        "rss_interpreter_gib": _gib(_status_kib("VmRSS") * 1024),
    }
    sampler = _Sampler()
    sampler.start()
    steps = {}
    original_occurrences = execute.Corpus._occurrences
    original_library = execute.Corpus._library

    def occurrences(self: execute.Corpus) -> None:
        steps["rss_open_gib"] = _gib(_status_kib("VmRSS") * 1024)
        steps["anon_open_gib"] = _gib(_anon())
        start = time.perf_counter()
        original_occurrences(self)
        steps["index_s"] = round(time.perf_counter() - start, 1)
        steps["rss_index_gib"] = _gib(_status_kib("VmRSS") * 1024)
        steps["anon_index_gib"] = _gib(_anon())

    def library(self: execute.Corpus):  # noqa: ANN202
        start = time.perf_counter()
        built = original_library(self)
        steps.setdefault("library_s", round(time.perf_counter() - start, 1))
        return built

    execute.Corpus._occurrences = occurrences
    execute.Corpus._library = library
    opened = time.perf_counter()
    corpus = execute.Corpus(
        "/artifacts/projections/**/*.parquet",
        "/artifacts/structures/**/*.parquet",
        resolver={}.__getitem__,
        pivots_dir="/artifacts/pivots",
        occurrences_dir="/artifacts/occurrences" if route == "view" else None,
        require_occurrences=route == "view",
        memory_limit=os.environ.get("DUCKDB_MEMORY_LIMIT"),
    )
    result["open_s"] = round(time.perf_counter() - opened, 1)
    sampler.stopped.set()
    sampler.join()
    result.update(steps)
    result["rss_warm_gib"] = _gib(_status_kib("VmRSS") * 1024)
    result["anon_warm_gib"] = _gib(_anon())
    result["peak_rss_gib"] = _gib(max(sampler.peak_rss, _status_kib("VmHWM") * 1024))
    result["peak_anon_gib"] = _gib(sampler.peak_anon)
    connection = corpus._connection
    result["duckdb_memory_limit"] = connection.execute(
        "SELECT current_setting('memory_limit')"
    ).fetchone()[0]
    result["duckdb_warm"] = {
        tag: _gib(value)
        for tag, value in connection.execute(
            "SELECT tag, memory_usage_bytes FROM duckdb_memory() "
            "WHERE memory_usage_bytes > 0"
        ).fetchall()
    }
    print(json.dumps(result), flush=True)
    corpus.close()


if __name__ == "__main__":
    main()
