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

"""Tallies checks.csv by route and severity, and checks it against validations.py.

checks.csv holds one row per ``context.error`` or ``context.warn`` call site in
ord_schema/validations.py. Given --validations, this also confirms the CSV names every
call site at its line and with its severity, so the inventory cannot silently drift from
the module it describes.
"""

import argparse
import collections
import csv
import pathlib
import re
import sys

_ROUTES = ("field", "cel", "code", "dataset")


def call_sites(path: pathlib.Path) -> dict[int, str]:
    """Returns each finding call site in validations.py, by line, with its severity."""
    sites = {}
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        match = re.search(r"context\.(error|warn)\(", line)
        if match:
            sites[number] = "error" if match.group(1) == "error" else "warning"
    return sites


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--checks", type=pathlib.Path, default=pathlib.Path(__file__).with_name("checks.csv")
    )
    parser.add_argument("--validations", type=pathlib.Path)
    args = parser.parse_args()
    with args.checks.open() as handle:
        rows = list(csv.DictReader(handle))
    if args.validations is not None:
        expected = call_sites(args.validations)
        recorded = {int(row["line"]): row["severity"] for row in rows}
        if recorded != expected:
            missing = sorted(set(expected) - set(recorded))
            extra = sorted(set(recorded) - set(expected))
            changed = sorted(
                line for line in set(expected) & set(recorded)
                if expected[line] != recorded[line]
            )
            sys.exit(f"checks.csv disagrees: missing {missing}, extra {extra}, severity {changed}")
        print(f"checks.csv matches all {len(expected)} call sites")
    counts = collections.Counter((row["route"], row["severity"]) for row in rows)
    instances = collections.Counter()
    for row in rows:
        instances[row["route"]] += int(row["instances"])
    print(f"{'route':8} {'errors':>6} {'warnings':>8} {'sites':>5} {'instances':>9}")
    for route in _ROUTES:
        errors, warnings = counts[(route, "error")], counts[(route, "warning")]
        print(f"{route:8} {errors:6d} {warnings:8d} {errors + warnings:5d} {instances[route]:9d}")
    print(f"{'total':8} {sum(counts[(r, 'error')] for r in _ROUTES):6d} "
          f"{sum(counts[(r, 'warning')] for r in _ROUTES):8d} {len(rows):5d} "
          f"{sum(instances.values()):9d}")


if __name__ == "__main__":
    main()
