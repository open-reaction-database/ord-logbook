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

"""Build the evaluation set: the name-only candidate names, with ORD row counts.

Reuses the 2026-07-11 name-only inventory: `resolver_results.tsv.gz` holds the 46,831
names that survived junk filtering, along with what OPSIN/CIR made of each one, and the
two count files hold how many ORD rows carry each name. The join gives a set that can be
scored both by unique name and by row coverage, and separates the names PubChem is
actually needed for (the OPSIN misses) from the ones already handled.

Writes `testset.tsv` with columns name, rows, prior (opsin | cir | none).
"""

import csv
import gzip
import pathlib

PRIOR = pathlib.Path("../2026-07-11-name-only-compounds")
OUT = pathlib.Path("testset.tsv")

counts: dict[str, int] = {}
for path, opener in (
    (PRIOR / "name_only_compounds.tsv.gz", gzip.open),
    (PRIOR / "name_only_product_compounds.tsv", open),
):
    with opener(path, mode="rt") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader)  # header: count, name
        for count, name in reader:
            counts[name] = counts.get(name, 0) + int(count)

rows = []
with gzip.open(PRIOR / "resolver_results.tsv.gz", mode="rt") as handle:
    reader = csv.reader(handle, delimiter="\t")
    next(reader)  # header: name, smiles, resolver
    for name, smiles, resolver in reader:
        prior = resolver.split("/")[0].lower() if smiles else "none"
        rows.append((name, counts.get(name, 0), "cir" if prior == "nci" else prior))

with OUT.open("w", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["name", "rows", "prior"])
    writer.writerows(rows)

by_prior: dict[str, list[int]] = {}
for _, count, prior in rows:
    by_prior.setdefault(prior, []).append(count)
for prior, counts_ in sorted(by_prior.items()):
    print(f"{prior}: {len(counts_)} names, {sum(counts_)} rows")
print(f"total: {len(rows)} names, {sum(c for _, c, _ in rows)} rows")
