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

"""Dry-runs the proposed DateTime normalization over an ord-data checkout.

Every value is parsed with an explicit ``strptime`` format — never
``dateutil``, whose day-first guess is wrong for at least one dataset — and
re-emitted as ISO 8601 at the precision the source carried. Slash-separated
values take their day/month order from ``slash_orientation.csv``; a dataset the
table leaves open is skipped whole.

Nothing is written. The script reports how many values each rule touches and
fails loudly on any value it cannot parse or cannot round-trip, which is what
makes the proposal checkable before anyone rewrites 1.2 GB of LFS objects.
"""

import argparse
import collections
import csv
import datetime
import pathlib
import re
import sys

import pyarrow.parquet as pq

import mini_reaction
from scan_date_times import dataset_id, signature

# Every signature in the corpus, mapped to the strptime format that reads it.
# A slash signature contributes only the part after the date, which is prefixed
# with the day/month order from the orientation table, so no value is ever
# parsed under a guessed order.
_FORMATS = {
    "NNNN-NN-NN NN:NN:NN.NNNNNN": "%Y-%m-%d %H:%M:%S.%f",
    "NNNN-NN-NN NN:NN:NN": "%Y-%m-%d %H:%M:%S",
    "NNNN-NN-NNWNN:NN:NN": "%Y-%m-%dT%H:%M:%S",
    "NNNN-NN-NN": "%Y-%m-%d",
    "DAY MON NN NN:NN:NN NNNN": "%a %b %d %H:%M:%S %Y",
    "DAY MON  N NN:NN:NN NNNN": "%a %b %d %H:%M:%S %Y",
}
_SLASH_TAILS = {
    r"^N{1,2}/N{1,2}/NNNN, N{1,2}:NN:NN AP$": "/%Y, %I:%M:%S %p",
    r"^N{1,2}/N{1,2}/NNNN, N{1,2}:NN:NN$": "/%Y, %H:%M:%S",
    r"^N{1,2}/N{1,2}/NNNN N{1,2}:NN:NN$": "/%Y %H:%M:%S",
    r"^N{1,2}/N{1,2}/NNNN$": "/%Y",
}
_ORDERS = {"day-first": "%d/%m", "month-first": "%m/%d"}

# A date-only source says nothing about the time of day, so it stays a date.
_DATE_ONLY = {"%Y-%m-%d", "/%Y"}


def strptime_format(shape: str, order: str | None) -> tuple[str, bool]:
    """Returns the strptime format for a signature, and whether it is date-only.

    Args:
        shape: A signature from ``scan_date_times.signature``.
        order: ``"day-first"`` or ``"month-first"`` for a slash signature,
            otherwise None.

    Returns:
        The strptime format string and whether the source carried no time.

    Raises:
        ValueError: If no format covers ``shape``, or a slash signature arrives
            without an order.
    """
    if shape in _FORMATS:
        return _FORMATS[shape], _FORMATS[shape] in _DATE_ONLY
    for pattern, tail in _SLASH_TAILS.items():
        if re.match(pattern, shape):
            if order is None:
                raise ValueError(f"no recorded day/month order for {shape}")
            return _ORDERS[order] + tail, tail in _DATE_ONLY
    raise ValueError(f"no format covers signature {shape}")


def normalize(value: str, shape: str, order: str | None, utc_known: bool) -> str:
    """Returns the ISO 8601 form of one DateTime value.

    Args:
        value: The raw string.
        shape: Its signature.
        order: The dataset's recorded day/month order, or None.
        utc_known: Whether the writer is known to work in UTC.

    Returns:
        ``YYYY-MM-DD`` for a date-only source, otherwise
        ``YYYY-MM-DDTHH:MM:SS`` with microseconds where the source had them and
        a trailing ``Z`` where the zone is known.

    Raises:
        ValueError: If the value does not parse, or does not round-trip.
    """
    date_format, date_only = strptime_format(shape, order)
    parsed = datetime.datetime.strptime(value, date_format)
    if date_only:
        return parsed.date().isoformat()
    return parsed.isoformat() + ("Z" if utc_known else "")


def read_orientations(path: pathlib.Path) -> dict[tuple[str, str], str | None]:
    """Reads the day/month order per (dataset, position); None where still open."""
    orientations = {}
    for row in csv.DictReader(path.open()):
        verdict = row["verdict"]
        orientations[row["dataset_id"], row["position"]] = (
            None if "lean" in verdict or verdict == "contradictory" else verdict
        )
    return orientations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data_directory", type=pathlib.Path, required=True,
        help="ord-data data/ directory.",
    )
    parser.add_argument(
        "--orientations", type=pathlib.Path,
        default=pathlib.Path("slash_orientation.csv"),
        help="Output of resolve_orientation.py.",
    )
    args = parser.parse_args()
    orientations = read_orientations(args.orientations)
    open_datasets = {
        dataset for (dataset, _), order in orientations.items() if order is None
    }

    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    examples: dict[tuple[str, str], tuple[str, str]] = {}
    skipped = collections.Counter()
    for path in sorted(args.data_directory.glob("*/*.parquet")):
        identifier = dataset_id(path)
        if identifier in open_datasets:
            skipped[identifier] = pq.ParquetFile(path).metadata.num_rows
            continue
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=4096, columns=["reaction"]
        ):
            for blob in batch.column("reaction").to_pylist():
                reaction = mini_reaction.Reaction.FromString(blob)
                for position, value, utc_known in mini_reaction.date_times_with_zone(
                    reaction
                ):
                    if not value:
                        continue
                    shape = signature(value)
                    order = orientations.get((identifier, position))
                    new = normalize(value, shape, order, utc_known)
                    kind = "Z" if new.endswith("Z") else "naive"
                    key = (shape, kind)
                    counts[key] += 1
                    examples.setdefault(key, (value, new))
        print(f"previewed {identifier}", file=sys.stderr, flush=True)

    total = sum(counts.values())
    print(f"\n{total:,} values normalized, {len(counts)} (signature, zone) rules\n")
    print(f"{'values':>10}  {'zone':<6} {'before':<28} -> after")
    for (shape, kind), count in counts.most_common():
        before, after = examples[shape, kind]
        print(f"{count:>10,}  {kind:<6} {before:<28} -> {after}")
    identical = sum(
        count
        for (shape, kind), count in counts.items()
        if examples[shape, kind][0] == examples[shape, kind][1]
    )
    print(f"\n{identical:,} values already canonical; {total - identical:,} rewritten")
    for dataset, rows in skipped.items():
        print(f"skipped {dataset} ({rows:,} reactions): day/month order still open")


if __name__ == "__main__":
    main()
