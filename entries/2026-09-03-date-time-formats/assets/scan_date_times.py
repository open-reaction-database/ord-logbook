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

"""Inventories every DateTime value in an ord-data checkout by surface format.

Each value is reduced to a shape signature — digit runs become runs of ``N``,
month and weekday names become ``MON`` and ``DAY``, ``AM``/``PM`` becomes
``AP``, any other word becomes ``W``, and punctuation and spacing are kept
verbatim. Two values share a signature exactly when they share a format, so
counting signatures per dataset and schema position says both which formats
exist and whether a dataset holds more than one.

Writes one CSV row per (dataset, schema position, signature).
"""

import argparse
import collections
import csv
import pathlib
import re
import sys

import pyarrow.parquet as pq

import mini_reaction

_WEEKDAYS = (
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    "|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun"
)
_MONTHS = (
    "january|february|march|april|may|june|july|august"
    "|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
)
_TOKEN = re.compile(
    rf"(?P<weekday>\b(?:{_WEEKDAYS})\b\.?)"
    rf"|(?P<month>\b(?:{_MONTHS})\b\.?)"
    r"|(?P<meridiem>\b[ap]\.?m\.?\b)"
    r"|(?P<digits>\d+)"
    r"|(?P<word>[A-Za-z]+)",
    re.IGNORECASE,
)
_NAMED = {"weekday": "DAY", "month": "MON", "meridiem": "AP"}


def signature(value: str) -> str:
    """Reduces a DateTime string to its format signature.

    Args:
        value: Raw DateTime string.

    Returns:
        The signature, with separators and field widths preserved.
    """

    def replace(match: re.Match[str]) -> str:
        if match.lastgroup == "digits":
            return "N" * len(match.group())
        if match.lastgroup == "word":
            return "W"
        return _NAMED[match.lastgroup]

    return _TOKEN.sub(replace, value.strip())


def dataset_id(path: pathlib.Path) -> str:
    """Returns the bare dataset ID for a ``data/xx/ord_dataset-<id>.parquet``."""
    return path.stem.removeprefix("ord_dataset-")


def scan(data_directory: pathlib.Path) -> dict:
    """Counts format signatures across every dataset under ``data_directory``.

    Args:
        data_directory: An ord-data ``data/`` directory with LFS objects
            materialized.

    Returns:
        A mapping of (dataset ID, schema position, signature) to
        ``[count, first example]``.
    """
    cells = collections.defaultdict(lambda: [0, None])
    for path in sorted(data_directory.glob("*/*.parquet")):
        identifier = dataset_id(path)
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4096, columns=["reaction"]):
            for blob in batch.column("reaction").to_pylist():
                reaction = mini_reaction.Reaction.FromString(blob)
                for position, value in mini_reaction.date_times(reaction):
                    cell = cells[identifier, position, signature(value)]
                    cell[0] += 1
                    if cell[1] is None:
                        cell[1] = value
        print(f"scanned {identifier}", file=sys.stderr, flush=True)
    return cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data_directory",
        type=pathlib.Path,
        required=True,
        help="ord-data data/ directory.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("date_time_formats.csv"),
        help="Destination CSV.",
    )
    args = parser.parse_args()
    cells = scan(args.data_directory)
    with args.output.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset_id", "position", "signature", "count", "example"])
        for (identifier, position, shape), (count, example) in sorted(cells.items()):
            writer.writerow([identifier, position, shape, count, example])
    print(f"wrote {len(cells)} rows to {args.output}")


if __name__ == "__main__":
    main()
