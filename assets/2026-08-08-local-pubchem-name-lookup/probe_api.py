"""Measure a live name-resolution service: latency, hit rate, throttle state.

Hits the same endpoints `ord_schema.resolvers` uses — PubChem PUG REST by default,
NCI/CADD CIR with `--service cir` — on a random sample of the name-only names, pacing
requests at PubChem's documented ceiling. Records the `X-Throttling-Control` header
alongside each response so a PubChem run shows how close the service considers us to a
block, not just whether we got one.

A name matching several CIDs comes back as one SMILES per line, so the line count is
recorded too. `resolve_name` hands the whole body to RDKit, which parses the first line
and discards the rest, so a multi-answer response is silently taken as the first one
(ord-schema#952).

Usage: probe_api.py TESTSET SAMPLE_SIZE OUT.tsv [--service pubchem] [--names FILE]
                   [--prior none] [--rate 3.0]
"""

import argparse
import csv
import gzip
import random
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SECONDS = 10
SERVICES = {
    "pubchem": (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}"
        "/property/IsomericSMILES/txt"
    ),
    "cir": "https://cactus.nci.nih.gov/chemical/structure/{name}/smiles",
}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("testset")
parser.add_argument("sample_size", type=int)
parser.add_argument("out")
parser.add_argument("--prior", default="none", help="filter to names with this prior outcome")
parser.add_argument("--names", help="restrict the sample to the names in this file")
parser.add_argument("--rate", type=float, default=3.0, help="requests per second")
parser.add_argument("--service", choices=sorted(SERVICES), default="pubchem")
parser.add_argument("--seed", type=int, default=20260808)
args = parser.parse_args()

opener = gzip.open if args.testset.endswith(".gz") else open
with opener(args.testset, mode="rt") as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    names = [row["name"] for row in reader if args.prior == "all" or row["prior"] == args.prior]
if args.names:
    names_opener = gzip.open if args.names.endswith(".gz") else open
    with names_opener(args.names, mode="rt") as handle:
        wanted = {line.rstrip("\n") for line in handle}
    names = [name for name in names if name in wanted]
random.Random(args.seed).shuffle(names)
sample = names[: args.sample_size]

interval = 1.0 / args.rate
results = []
start = time.monotonic()
for index, name in enumerate(sample):
    deadline = start + index * interval
    delay = deadline - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    url = SERVICES[args.service].format(name=urllib.parse.quote(name, safe=""))
    request_start = time.monotonic()
    status, smiles, throttle, lines = "", "", "", 0
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            status = str(response.status)
            throttle = response.headers.get("X-Throttling-Control", "")
            body = response.read().decode(errors="replace").strip().split("\n")
            smiles, lines = body[0], len(body)
    except urllib.error.HTTPError as error:
        status = str(error.code)
        throttle = error.headers.get("X-Throttling-Control", "")
    except Exception as error:  # noqa: BLE001 - transport failures are a measured outcome
        status = type(error).__name__
    elapsed = time.monotonic() - request_start
    results.append((name, status, smiles, lines, round(elapsed, 3), throttle))

with open(args.out, "w", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["name", "status", "smiles", "lines", "seconds", "throttle"])
    writer.writerows(results)

statuses: dict[str, int] = {}
for _, status, *_ in results:
    statuses[status] = statuses.get(status, 0) + 1
latencies = sorted(row[4] for row in results)
hits = sum(1 for row in results if row[2])
multi = sum(1 for row in results if row[3] > 1)
print(f"n={len(results)} hits={hits} ({hits / len(results):.1%}) multi-cid={multi}")
print("statuses:", dict(sorted(statuses.items(), key=lambda kv: -kv[1])))
print(
    f"latency p50={latencies[len(latencies) // 2]:.3f}s "
    f"p95={latencies[int(len(latencies) * 0.95)]:.3f}s max={latencies[-1]:.3f}s"
)
print("last throttle:", results[-1][5])
