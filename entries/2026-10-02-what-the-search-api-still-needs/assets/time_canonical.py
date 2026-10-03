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

"""Times every canonical query in ord_schema.search.check against a built corpus.

Two measurements, written to --output as JSON and summarized on stdout:

1. Each canonical query's first ask on a freshly opened corpus, then the median of
   three repeats, in four configurations: pivot and occurrence artifacts or occurrence
   artifacts alone with no pivot built (pivot_budget_bytes=0), each with the corpus's
   default row bound and unbounded.
2. The first ask of three queries on a fresh corpus with and without
   ``Corpus.check_pivots()`` called at open, which separates the one-time cost of
   reaching a pivot level from the cost of the query itself.

Expects --artifacts to hold projections/, structures/, pivots/, and occurrences/ in
the layout ord_schema.artifacts.scripts writes.
"""

import argparse
import json
import logging
import pathlib
import statistics
import time

from ord_schema.search import check, execute, query

_REPEATS = 3
_WARMED = ("nested_quantifiers", "existential_quantifier", "substructure_screen")


def _open(root: pathlib.Path, **kwargs) -> execute.Corpus:
    """Opens the corpus under ``root`` with the given options."""
    return execute.Corpus(
        str(root / "projections" / "*" / "*.parquet"),
        str(root / "structures" / "*" / "*.parquet"),
        **kwargs,
    )


def _timed(corpus: execute.Corpus, request: query.Query) -> tuple[float, int]:
    """Returns how long one search took and how many rows it returned."""
    start = time.perf_counter()
    rows = corpus.search(request).num_rows
    return time.perf_counter() - start, rows


def measure_configurations(root: pathlib.Path) -> dict:
    """Returns first-ask and repeat timings for every query in every configuration."""
    configurations = {
        "pivots and occurrences": {
            "pivots_dir": str(root / "pivots"),
            "occurrences_dir": str(root / "occurrences"),
        },
        "occurrences, no pivots": {
            "occurrences_dir": str(root / "occurrences"),
            "pivot_budget_bytes": 0,
        },
    }
    bounds = {"default bound": execute.DEFAULT_MAX_ROWS, "unbounded": None}
    results = {}
    for configuration, options in configurations.items():
        for bound, max_rows in bounds.items():
            start = time.perf_counter()
            with _open(root, max_rows=max_rows, **options) as corpus:
                opened = time.perf_counter() - start
                timings = {}
                for entry in check.QUERIES:
                    request = query.Query.model_validate(entry["query"])
                    first, rows = _timed(corpus, request)
                    repeats = [_timed(corpus, request)[0] for _ in range(_REPEATS)]
                    timings[entry["name"]] = {
                        "first": first,
                        "repeat": statistics.median(repeats),
                        "rows": rows,
                    }
            label = f"{configuration}, {bound}"
            results[label] = {"open_seconds": opened, "queries": timings}
            slowest = max(timings.values(), key=lambda timing: timing["first"])["first"]
            over = sorted(name for name, timing in timings.items() if timing["first"] >= 1)
            print(f"{label}: open {opened:.1f}s, slowest first ask {slowest:.3f}s, over 1s: {over}")
    return results


def measure_warming(root: pathlib.Path) -> dict:
    """Returns first-ask timings with and without every pivot level reached at open."""
    by_name = {entry["name"]: entry for entry in check.QUERIES}
    results = {}
    for warm in (False, True):
        with _open(
            root,
            pivots_dir=str(root / "pivots"),
            occurrences_dir=str(root / "occurrences"),
        ) as corpus:
            start = time.perf_counter()
            if warm:
                corpus.check_pivots()
            spent = time.perf_counter() - start
            timings = {
                name: _timed(corpus, query.Query.model_validate(by_name[name]["query"]))[0]
                for name in _WARMED
            }
        label = "check_pivots at open" if warm else "no warming"
        results[label] = {"warm_seconds": spent, "first": timings}
        print(f"{label} ({spent:.1f}s): {timings}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    root = args.artifacts.expanduser()
    results = {
        "configurations": measure_configurations(root),
        "warming": measure_warming(root),
    }
    args.output.write_text(json.dumps(results, indent=1) + "\n")


if __name__ == "__main__":
    main()
