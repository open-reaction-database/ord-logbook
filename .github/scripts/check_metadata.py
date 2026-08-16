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

"""Check the metadata block each logbook entry opens with.

Every entry states its date, author, status, tags, and license in a bullet list
under the title. This verifies the fields are present and filled in, that the
stated date matches the entry's directory, and that the license is the one the
repository actually grants.

Run from the repository root:

    python3 .github/scripts/check_metadata.py
"""

import argparse
import re
import sys
from pathlib import Path

FIELD = re.compile(r"^- \*\*(?P<name>[A-Za-z]+):\*\*\s*(?P<value>.*)$")
PLACEHOLDER = re.compile(r"^<.*>$|^YYYY-MM-DD$|^draft \| final$")
SLUG = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-[a-z0-9-]+$")
LICENSE = "[CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)"
REQUIRED = ("Date", "Author", "Status", "Tags", "License")


def fields(path: Path) -> dict[str, str]:
    """Read the metadata bullets that open an entry.

    Args:
        path: Entry ``README.md`` to read.

    Returns:
        Field name mapped to its value. Scanning stops at the first section
        heading, so bolded bullets in the body are not mistaken for metadata.
    """
    found = {}
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            break
        match = FIELD.match(line)
        if match:
            found[match.group("name")] = match.group("value").strip()
    return found


def check(path: Path, root: Path) -> list[str]:
    """Check one entry's metadata block.

    Args:
        path: Entry ``README.md`` to check.
        root: Repository root, used to render paths in messages.

    Returns:
        One message per problem found, empty if the entry is clean.
    """
    problems = []
    rel = path.relative_to(root)
    found = fields(path)

    for name in REQUIRED:
        value = found.get(name)
        if value is None:
            problems.append(f"{rel}: missing metadata field: {name}")
        elif not value or PLACEHOLDER.match(value):
            problems.append(f"{rel}: {name} is still the template placeholder")

    slug = SLUG.match(path.parent.name)
    if not slug:
        problems.append(f"{rel}: directory is not named YYYY-MM-DD-slug")
    elif "Date" in found and found["Date"] != slug.group("date"):
        problems.append(
            f"{rel}: Date {found['Date']} does not match the directory date "
            f"{slug.group('date')}"
        )

    # Status wording is deliberately open — entries qualify it ("final (shipped
    # in ord-schema#965)"), so only an unedited template value is a problem.
    license_ = found.get("License", "")
    if license_ and license_ != LICENSE:
        problems.append(f"{rel}: License should read {LICENSE}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root", nargs="?", default=".", help="repository root to check"
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()

    entries = sorted(root.glob("entries/*/README.md"))
    problems = []
    for path in entries:
        problems.extend(check(path, root))

    for problem in problems:
        print(problem)
    print(f"checked {len(entries)} entries, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
