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

"""Compare local OPSIN (py2opsin, a JVM) against the EBI OPSIN web service.

`ord_schema.resolvers._opsin_resolve` calls https://www.ebi.ac.uk/opsin/ws/ over HTTP,
one request per name. OPSIN is a Java library, so the same parse can run in-process.
Whether that is an improvement depends entirely on how the caller batches: the jar reads
a whole file of names in one JVM, but a JVM start costs more than the HTTP round trip it
would replace.

Measures both shapes — one name per JVM, and the whole set in one JVM — and checks the
answers against the 2026-07-11 web-service results.

Usage: bench_opsin.py TESTSET PRIOR_RESULTS OUT.tsv [--single 20]
"""

import argparse
import csv
import gzip
import pathlib
import statistics
import time

from py2opsin import py2opsin

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("testset", type=pathlib.Path)
parser.add_argument("prior_results", type=pathlib.Path)
parser.add_argument("out", type=pathlib.Path)
parser.add_argument("--single", type=int, default=20, help="names to time one-per-JVM")
args = parser.parse_args()

opener = gzip.open if args.testset.suffix == ".gz" else open
with opener(args.testset, mode="rt") as handle:
    names = [row["name"] for row in csv.DictReader(handle, delimiter="\t")]

start = time.monotonic()
smiles = py2opsin(names)
batch_seconds = time.monotonic() - start
hits = {name: value for name, value in zip(names, smiles, strict=True) if value}

with args.out.open("w", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["name", "smiles"])
    writer.writerows((name, hits.get(name, "")) for name in names)

print(f"batch: {len(names):,} names in one JVM, {batch_seconds:.1f}s "
      f"({batch_seconds / len(names) * 1000:.2f} ms/name), {len(hits):,} hits")

timings = []
for name in names[: args.single]:
    single_start = time.monotonic()
    py2opsin(name)
    timings.append((time.monotonic() - single_start) * 1000)
timings.sort()
print(f"one name per JVM: p50 {timings[len(timings) // 2]:.0f} ms  "
      f"mean {statistics.mean(timings):.0f} ms  (n={len(timings)})")

with gzip.open(args.prior_results, mode="rt") as handle:
    web = {
        row["name"]: row["smiles"]
        for row in csv.DictReader(handle, delimiter="\t")
        if row["resolver"] == "OPSIN"
    }
print(f"\nweb-service hits (2026-07-11) {len(web):,}")
print(f"local hits                    {len(hits):,}")
print(f"local only                    {len(set(hits) - set(web)):,}")
print(f"web only                      {len(set(web) - set(hits)):,}")
differing = [name for name in set(hits) & set(web) if hits[name] != web[name]]
print(f"both, different SMILES string {len(differing):,}")
for name in differing[:10]:
    print(f"  {name!r}\n    local {hits[name]}\n    web   {web[name]}")
