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

"""Decides day-first versus month-first for the slash-separated DateTime values.

``12/05/2024`` is either 12 May or 5 December and the string does not say which,
so each dataset's slash-formatted values are settled against several kinds of
evidence, strongest first:

* a **confirmation** — evidence outside the corpus, such as the supplemental
  data attached to a submission pull request, recorded in ``_CONFIRMED``;
* a **witness** — one value whose first component exceeds 12 (day-first) or
  whose second does (month-first);
* an **upper bound** — a reaction's ``record_created`` precedes each of its
  ``record_modified`` events, and every value predates the last commit to touch
  the dataset in ord-data, so a reading landing after that bound is impossible;
* a **sibling** — a dataset added by the same commit is the same submission from
  the same contributor, so a settled sibling settles it too;
* the **format** — a 12-hour value with an uppercase meridiem and a comma is the
  ``en-US`` ``Date.toLocaleString()`` shape, and every locale that renders that
  shape is month-first;
* **proximity** — with none of the above, the reading that falls closer to the
  bound is reported as a lean, not a verdict.

Writes one CSV row per (dataset, schema position) that holds slash values.
"""

import argparse
import collections
import csv
import datetime
import pathlib
import re
import subprocess
import sys

import pyarrow.parquet as pq

import mini_reaction
from scan_date_times import dataset_id

_SLASH = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:[, ]+(\d{1,2}):(\d{2}):(\d{2})(?:\s*([AP])M)?)?$",
    re.IGNORECASE,
)
# The exact en-US Date.toLocaleString() rendering. Day-first locales that use a
# 12-hour clock render a lowercase meridiem, so an uppercase one pins the locale.
_EN_US = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}, \d{1,2}:\d{2}:\d{2} (?:AM|PM)$")
# Orientations settled outside the corpus, and where the answer came from.
# Keyed by (dataset ID, schema position).
_CONFIRMED = {
    # Confirmed against the supplemental data on ord-data#86.
    ("35a5a513f1dd44a3a97c88da99f81a00", "provenance.record_created.time"): (
        "month-first",
        "ord-data#86 supplemental data",
    ),
    # Confirmed against supplemental data on ord-data#188.
    ("d92976309c3a48a3a64a4cf5e7048086", "provenance.record_created.time"): (
        "month-first",
        "ord-data#188 supplemental data",
    ),
}
_UNAMBIGUOUS_FORMATS = (
    "%a %b %d %H:%M:%S %Y",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


def parse_slash(value: str, *, day_first: bool) -> datetime.datetime | None:
    """Parses a slash-separated value under one reading of the leading fields.

    Args:
        value: Raw DateTime string.
        day_first: Read the first component as the day rather than the month.

    Returns:
        The datetime, or None if the string is not slash-separated or the
        reading yields an impossible date.
    """
    match = _SLASH.match(value)
    if match is None:
        return None
    first, second, year, hour, minute, second_of_minute, meridiem = match.groups()
    day, month = (
        (int(first), int(second)) if day_first else (int(second), int(first))
    )
    hour = int(hour or 0)
    if meridiem is not None:
        hour = hour % 12 + (12 if meridiem.upper() == "P" else 0)
    try:
        return datetime.datetime(
            int(year), month, day, hour, int(minute or 0), int(second_of_minute or 0)
        )
    except ValueError:
        return None


def parse_unambiguous(value: str) -> datetime.datetime | None:
    """Parses a value in any of the corpus formats that cannot be misread."""
    for date_format in _UNAMBIGUOUS_FORMATS:
        try:
            return datetime.datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def first_added(repository: pathlib.Path, identifier: str) -> str:
    """Returns the hash of the commit that first added a dataset.

    Datasets added by one commit arrived in one submission, which is what makes
    a settled dataset evidence about its siblings.

    Args:
        repository: ord-data checkout.
        identifier: Bare dataset ID.

    Returns:
        The commit hash.
    """
    commits = subprocess.run(
        ["git", "log", "--all", "--diff-filter=A", "--format=%H",
         "--", f"*{identifier}*"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return commits[-1]


def last_touched(repository: pathlib.Path, identifier: str) -> datetime.datetime:
    """Returns the author date of the last commit to touch a dataset.

    Matches any path holding the dataset ID, so the Parquet file's pre-migration
    ``.pb.gz`` predecessor counts. This is a ceiling on every timestamp the file
    carries: a value written after it could not have been committed.

    Args:
        repository: ord-data checkout.
        identifier: Bare dataset ID.

    Returns:
        The naive local author date of the most recent such commit.
    """
    dates = subprocess.run(
        [
            "git", "log", "--all",
            "--format=%ad", "--date=format:%Y-%m-%dT%H:%M:%S",
            "--", f"*{identifier}*",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return datetime.datetime.fromisoformat(dates[0])


class Evidence:
    """Accumulates orientation evidence for one dataset and schema position."""

    def __init__(self, confirmed: str | None = None) -> None:
        self.confirmed = confirmed
        self.values = 0
        self.distinct: set[str] = set()
        self.day_first_witness = 0
        self.month_first_witness = 0
        self.bound: datetime.datetime | None = None
        self.day_first_latest: datetime.datetime | None = None
        self.month_first_latest: datetime.datetime | None = None
        self.all_en_us = True

    def add(self, value: str, bound: datetime.datetime) -> None:
        """Folds in one slash value and the tightest bound that applies to it."""
        match = _SLASH.match(value)
        self.values += 1
        self.distinct.add(value)
        self.all_en_us = self.all_en_us and _EN_US.match(value) is not None
        if int(match.group(1)) > 12:
            self.day_first_witness += 1
        elif int(match.group(2)) > 12:
            self.month_first_witness += 1
        self.bound = bound if self.bound is None else min(self.bound, bound)
        for day_first in (True, False):
            parsed = parse_slash(value, day_first=day_first)
            if parsed is None:
                continue
            attribute = "day_first_latest" if day_first else "month_first_latest"
            latest = getattr(self, attribute)
            setattr(self, attribute, parsed if latest is None else max(latest, parsed))

    def verdict(self) -> tuple[str, str]:
        """Returns the orientation and the strongest evidence supporting it."""
        if self.confirmed is not None:
            return self.confirmed, "confirmed"
        if self.day_first_witness and self.month_first_witness:
            return "contradictory", "witness"
        if self.day_first_witness:
            return "day-first", "witness"
        if self.month_first_witness:
            return "month-first", "witness"
        day_possible = (
            self.day_first_latest is not None and self.day_first_latest <= self.bound
        )
        month_possible = (
            self.month_first_latest is not None
            and self.month_first_latest <= self.bound
        )
        if month_possible and not day_possible:
            return "month-first", "bound"
        if day_possible and not month_possible:
            return "day-first", "bound"
        if not day_possible and not month_possible:
            return "contradictory", "bound"
        if self.all_en_us:
            return "month-first", "format"
        day_gap = self.bound - self.day_first_latest
        month_gap = self.bound - self.month_first_latest
        leaning = "month-first" if month_gap < day_gap else "day-first"
        return f"{leaning} (lean)", "proximity"


def promote_siblings(verdicts: dict, submissions: dict) -> dict:
    """Replaces a lean with the settled verdict of its co-submitted datasets.

    Args:
        verdicts: (dataset, position) -> (verdict, basis).
        submissions: Dataset ID -> hash of the commit that added it.

    Returns:
        ``verdicts`` with leans resolved where a sibling settles them.
    """
    settled = collections.defaultdict(set)
    for (identifier, _), (verdict, _) in verdicts.items():
        if "lean" not in verdict and verdict != "contradictory":
            settled[submissions[identifier]].add(verdict)
    promoted = {}
    for key, (verdict, basis) in verdicts.items():
        siblings = settled[submissions[key[0]]]
        if "lean" in verdict and len(siblings) == 1:
            promoted[key] = (siblings.pop(), "sibling")
        else:
            promoted[key] = (verdict, basis)
    return promoted


def collect(data_directory: pathlib.Path, repository: pathlib.Path) -> dict:
    """Gathers slash-value evidence for every dataset under ``data_directory``."""
    evidence: dict[tuple[str, str], Evidence] = {}
    for path in sorted(data_directory.glob("*/*.parquet")):
        identifier = dataset_id(path)
        committed = last_touched(repository, identifier)
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4096, columns=["reaction"]):
            for blob in batch.column("reaction").to_pylist():
                pairs = list(
                    mini_reaction.date_times(
                        mini_reaction.Reaction.FromString(blob)
                    )
                )
                modified = [
                    parsed
                    for position, value in pairs
                    if position == mini_reaction.RECORD_MODIFIED
                    for parsed in [parse_unambiguous(value)]
                    if parsed is not None
                ]
                for position, value in pairs:
                    if _SLASH.match(value) is None:
                        continue
                    bound = committed
                    if position == mini_reaction.RECORD_CREATED and modified:
                        bound = min(modified)
                    key = (identifier, position)
                    if key not in evidence:
                        confirmed, _ = _CONFIRMED.get(key, (None, None))
                        evidence[key] = Evidence(confirmed)
                    evidence[key].add(value, bound)
        print(f"scanned {identifier}", file=sys.stderr, flush=True)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=pathlib.Path,
        required=True,
        help="ord-data checkout, read for both data and git history.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("slash_orientation.csv"),
        help="Destination CSV.",
    )
    args = parser.parse_args()
    evidence = collect(args.repository / "data", args.repository)
    submissions = {
        identifier: first_added(args.repository, identifier)
        for identifier, _ in evidence
    }
    verdicts = promote_siblings(
        {key: item.verdict() for key, item in evidence.items()}, submissions
    )
    with args.output.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "dataset_id", "position", "values", "distinct_values",
                "day_first_witnesses", "month_first_witnesses", "bound",
                "day_first_latest", "month_first_latest", "verdict", "basis",
            ]
        )
        for (identifier, position), item in sorted(evidence.items()):
            verdict, basis = verdicts[identifier, position]
            writer.writerow(
                [
                    identifier, position, item.values, len(item.distinct),
                    item.day_first_witness, item.month_first_witness,
                    item.bound.isoformat(),
                    item.day_first_latest.isoformat()
                    if item.day_first_latest
                    else "",
                    item.month_first_latest.isoformat()
                    if item.month_first_latest
                    else "",
                    verdict,
                    _CONFIRMED[identifier, position][1]
                    if basis == "confirmed"
                    else basis,
                ]
            )
    print(f"wrote {len(evidence)} rows to {args.output}")


if __name__ == "__main__":
    main()
