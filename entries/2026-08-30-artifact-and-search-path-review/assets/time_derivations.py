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

"""Times each derivation over the corpus's dominant dataset.

Finding 3 of the review asks whether ``ARTIFACT_VERSION`` should stay shared across
artifact types. What decides it is what a needless re-derive costs, and that had never
been measured: one 1.0 GB source is 96% of this corpus, so its timings are the corpus's.
"""

import argparse, json, pathlib, time
from ord_schema.artifacts import occurrences, pivot, projection, structures

LEVELS = ("inputs.components", "outcomes.products",
          "outcomes.products.measurements", "workups.input.components")


def main(args):
    """Derives projection, structures, pivots, and occurrences in turn, timing each."""
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(args.source)
    report = {"source_bytes": source.stat().st_size}

    projected = out / "projection.parquet"
    start = time.perf_counter()
    projection.write_projection(source, projected)
    report["projection_seconds"] = time.perf_counter() - start
    report["projection_bytes"] = projected.stat().st_size

    structured = out / "structures.parquet"
    start = time.perf_counter()
    structures.write_structures(projected, structured)
    report["structures_seconds"] = time.perf_counter() - start
    report["structures_bytes"] = structured.stat().st_size

    report["pivot_seconds"] = {}
    pivots = out / "pivots"
    for level in LEVELS:
        target = pivots / level / "one.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        pivot.write_pivot(projected, target, level_path=level)
        report["pivot_seconds"][level] = time.perf_counter() - start
    report["pivot_total_seconds"] = sum(report["pivot_seconds"].values())

    report["occurrence_seconds"] = {}
    for path, (level, _) in occurrences.PATHS.items():
        target = out / "occurrences" / path / "one.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        occurrences.write_occurrences(
            pivots / level.path / "one.parquet", target, path=path
        )
        report["occurrence_seconds"][path] = time.perf_counter() - start
    report["occurrence_total_seconds"] = sum(report["occurrence_seconds"].values())
    print(json.dumps(report, indent=2))


def parse_args(argv=None):
    """Parses command-line arguments."""
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    return p.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
