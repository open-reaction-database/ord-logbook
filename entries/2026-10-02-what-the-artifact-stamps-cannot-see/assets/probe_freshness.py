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

"""Asks a built corpus what its freshness check can and cannot see.

Three probes over the projections under --projections, each printing what
``base.is_current`` answers and why:

1. A dataset whose day/month verdict moves from undecided to day-first. Nothing
   stamped changes, so the projection reports current while its timestamps stay
   null -- the case this entry is about.
2. The dates those undecided projections hold, spelled versus parsed, which is
   what a wrong answer to probe 1 costs.
3. Whether each hardcoded day-first verdict is one the value scan would reach on
   its own, which says how much of the table is load-bearing.

Usage:
    python probe_freshness.py --projections=~/ord/artifacts/projections
"""

import argparse
import pathlib

import duckdb

from ord_schema.artifacts import base, projection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projections",
        required=True,
        help="Directory holding the projections to probe, searched recursively",
    )
    return parser.parse_args(argv)


def _projection_for(root: pathlib.Path, dataset_id: str) -> pathlib.Path | None:
    """Returns the projection of one source dataset, or None where there is none.

    Args:
        root: Directory to search recursively.
        dataset_id: The source dataset's ``ord_dataset-`` ID.

    Returns:
        The path, or None.
    """
    for path in sorted(root.rglob("*.parquet")):
        if base.load_stamps(path).source_dataset_id == dataset_id:
            return path
    return None


def probe_resolved_verdict(root: pathlib.Path) -> None:
    """Reports what freshness answers when an undecided verdict is settled in code.

    Args:
        root: Directory holding the projections.
    """
    print("1. A verdict settled in code, for a source whose bytes have not moved")
    for dataset_id in sorted(projection._UNDECIDED):
        path = _projection_for(root, dataset_id)
        if path is None:
            print(f"   {dataset_id[:28]}: no projection found")
            continue
        stamps = base.load_stamps(path)
        # Settle it the way a one-line edit to the table would.
        undecided = projection._UNDECIDED
        day_first = projection._DAY_FIRST
        projection._UNDECIDED = frozenset(undecided - {dataset_id})
        projection._DAY_FIRST = frozenset(day_first | {dataset_id})
        try:
            current = base.is_current(
                path, projection.ARTIFACT, stamps.source_md5, projection.SCHEMA
            )
            missing = base.missing_columns(path, projection.SCHEMA)
            stamped = base.stamps_are_current(stamps, projection.ARTIFACT)
        finally:
            projection._UNDECIDED = undecided
            projection._DAY_FIRST = day_first
        print(
            f"   {dataset_id[:28]}: is_current={current}, "
            f"missing_columns={missing}, stamps_are_current={stamped}"
        )


def probe_unparsed_dates(root: pathlib.Path) -> None:
    """Reports how many dates the undecided projections spell but do not parse.

    Args:
        root: Directory holding the projections.
    """
    print("2. What those projections hold today")
    for dataset_id in sorted(projection._UNDECIDED):
        path = _projection_for(root, dataset_id)
        if path is None:
            continue
        rows, spelled, parsed = duckdb.sql(f"""
            SELECT count(*),
                   count(provenance.record_created.time.value),
                   count(provenance.record_created.time.timestamp)
            FROM read_parquet('{path}')
        """).fetchone()
        print(
            f"   {dataset_id[:28]}: {rows} rows, {spelled} dates spelled, "
            f"{parsed} parsed"
        )


def probe_table_redundancy(root: pathlib.Path) -> None:
    """Reports which hardcoded day-first verdicts the value scan reaches alone.

    Args:
        root: Directory holding the projections.
    """
    print("3. Which day-first verdicts the scan would reach without the table")
    for dataset_id in sorted(projection._DAY_FIRST):
        path = _projection_for(root, dataset_id)
        if path is None:
            print(f"   {dataset_id[:28]}: no projection found")
            continue
        values = duckdb.sql(f"""
            SELECT provenance.record_created.time.value
            FROM read_parquet('{path}')
            WHERE provenance.record_created.time.value IS NOT NULL
        """).fetchall()
        witnessed = projection.day_first_dates([value for (value,) in values])
        verdict = {True: "day-first", False: "month-first", None: "undecided"}[
            witnessed
        ]
        print(f"   {dataset_id[:28]}: scan alone says {verdict}")


def main(args: argparse.Namespace) -> None:
    """Runs all three probes.

    Args:
        args: Parsed arguments, read for ``projections``.
    """
    root = pathlib.Path(args.projections).expanduser()
    probe_resolved_verdict(root)
    probe_unparsed_dates(root)
    probe_table_redundancy(root)


if __name__ == "__main__":
    main(parse_args())
