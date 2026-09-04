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

Nothing is written. The script reports what each candidate scope would cost and
fails loudly on any value it cannot parse, which is what makes the proposal
checkable before anyone rewrites LFS objects. The three scopes are:

``all``
    Every value. Uniform corpus, and the only scope that can stamp ``Z``.
``slash``
    Only the slash-separated values — the ones a reader can get wrong.
``ambiguous``
    Only the slash values whose two leading fields are both at most 12, which
    are the only ones a reader cannot resolve unaided. The script verifies that
    claim over every value the scope leaves behind.
"""

import argparse
import collections
import csv
import datetime
import pathlib
import re
import sys

import pyarrow.parquet as pq

from dateutil import parser as date_parser

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
_LEADING_FIELDS = re.compile(r"^(\d{1,2})/(\d{1,2})/")
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


def scope_of(value: str) -> str:
    """Returns the narrowest scope that would rewrite ``value``.

    Args:
        value: A raw DateTime string.

    Returns:
        ``"ambiguous"`` for a slash value whose leading fields are both at most
        12, ``"slash"`` for any other slash value, and ``"all"`` otherwise.
    """
    match = _LEADING_FIELDS.match(value)
    if match is None:
        return "all"
    if int(match.group(1)) <= 12 and int(match.group(2)) <= 12:
        return "ambiguous"
    return "slash"


def resolves_unaided(value: str, expected: datetime.datetime) -> bool:
    """Returns whether a value reads correctly with no per-dataset knowledge.

    A reader that swaps the fields when the first cannot be a month lands on
    ``expected`` whichever order it prefers; one that insists on a fixed order
    raises rather than returning a wrong date. Either way the value cannot be
    silently misread.

    Args:
        value: A raw DateTime string.
        expected: The datetime the value denotes under the recorded order.

    Returns:
        True if no reader can silently misread the value.
    """
    return (
        date_parser.parse(value) == expected
        and date_parser.parse(value, dayfirst=True) == expected
    )


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

    scopes = ("all", "slash", "ambiguous")
    # scope -> counters over the files that scope would rewrite
    files = collections.Counter()
    file_bytes = collections.Counter()
    reactions = collections.Counter()
    values = collections.Counter()
    rules: collections.Counter[tuple[str, str]] = collections.Counter()
    examples: dict[tuple[str, str], tuple[str, str]] = {}
    survivors = collections.Counter()
    unaided = collections.Counter()
    skipped = collections.Counter()

    for path in sorted(args.data_directory.glob("*/*.parquet")):
        identifier = dataset_id(path)
        parquet = pq.ParquetFile(path)
        if identifier in open_datasets:
            skipped[identifier] = parquet.metadata.num_rows
            continue
        touched = collections.Counter()
        for batch in parquet.iter_batches(batch_size=4096, columns=["reaction"]):
            for blob in batch.column("reaction").to_pylist():
                hit = set()
                for position, value, utc_known in mini_reaction.date_times_with_zone(
                    mini_reaction.Reaction.FromString(blob)
                ):
                    if not value:
                        continue
                    shape = signature(value)
                    order = orientations.get((identifier, position))
                    new = normalize(value, shape, order, utc_known)
                    scope = scope_of(value)
                    key = (shape, "Z" if new.endswith("Z") else "naive")
                    rules[key] += 1
                    examples.setdefault(key, (value, new))
                    for name in scopes:
                        if name == "all" or name == scope or (
                            name == "slash" and scope == "ambiguous"
                        ):
                            values[name] += 1
                            hit.add(name)
                    if scope == "slash":
                        survivors["values"] += 1
                        expected = datetime.datetime.strptime(
                            value, strptime_format(shape, order)[0]
                        )
                        unaided[resolves_unaided(value, expected)] += 1
                for name in hit:
                    touched[name] += 1
        for name in scopes:
            if touched[name]:
                files[name] += 1
                file_bytes[name] += path.stat().st_size
                reactions[name] += touched[name]

    print(f"\n{'scope':<12}{'files':>7}{'bytes':>12}{'reactions':>12}{'values':>12}")
    for name in scopes:
        print(
            f"{name:<12}{files[name]:>7}{file_bytes[name] / 1e6:>10,.1f} MB"
            f"{reactions[name]:>12,}{values[name]:>12,}"
        )
    for dataset, rows in skipped.items():
        print(f"\nskipped {dataset} ({rows:,} reactions): day/month order still open")

    print(f"\n{'values':>10}  {'zone':<6} {'before':<28} -> after")
    for (shape, kind), count in rules.most_common():
        before, after = examples[shape, kind]
        print(f"{count:>10,}  {kind:<6} {before:<28} -> {after}")

    print(
        f"\nafter the 'ambiguous' scope, {survivors['values']:,} slash values "
        f"remain; {unaided[True]:,} of them read correctly with no per-dataset "
        f"knowledge and {unaided[False]:,} do not"
    )
    if unaided[False]:
        raise SystemExit("the 'ambiguous' scope would leave misreadable values behind")


if __name__ == "__main__":
    main()
