"""Resolve the union of name-only compound names to SMILES via ord-schema's resolvers.

PubChem is disabled (rate limits); the remaining backends are NCI/CADD CIR and OPSIN, tried in
that order. Resumable and incremental: only definitive outcomes (resolved / genuinely unresolved)
are written, so a rerun retries names that hit a transient failure (rate limit, timeout, 5xx)
while skipping the ones already settled.

Classification per backend:
  * non-empty return           -> resolved
  * HTTP 404, or CIR's 500 for an unknown name -> a miss for that backend (try the next)
  * HTTP 429/502/503/504, timeout, connection error -> transient (retry the whole name later)
"""

import csv
import os
import socket
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import ord_schema.resolvers as resolvers

socket.setdefaulttimeout(20)

# PubChem is skipped (rate limits) and NCI/CADD CIR (cactus) is unreachable / blocking us
# (connection-level URLError on every request), so OPSIN is the only working backend. OPSIN
# parses systematic IUPAC names but rejects trade/trivial names, so recovery is limited to the
# systematic-name subset.
resolvers._NAME_RESOLVERS = {
    name: func for name, func in resolvers._NAME_RESOLVERS.items() if name == "OPSIN"
}

UNION_PATH, OUT_PATH = sys.argv[1], sys.argv[2]
WORKERS = 6
_TRANSIENT_CODES = {429, 502, 503, 504}


def resolve(name: str) -> tuple[str, str, str]:
    """Returns (smiles, resolver, status); status is resolved | unresolved | transient."""
    transient = False
    for who, func in resolvers._NAME_RESOLVERS.items():
        try:
            smiles = func("name", name)
            if smiles:
                return smiles, who, "resolved"
        except urllib.error.HTTPError as error:
            if error.code in _TRANSIENT_CODES:
                transient = True
            # 404 / CIR-500 (unknown name): a genuine miss for this backend; try the next.
        except Exception:  # noqa: BLE001  (timeout, URLError, connection reset -> retry later)
            transient = True
    return "", "", ("transient" if transient else "unresolved")


done: set[str] = set()
if os.path.exists(OUT_PATH):
    with open(OUT_PATH, newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        for row in reader:
            if row:
                done.add(row[0])

names = [line.rstrip("\n") for line in open(UNION_PATH) if line.strip()]
todo = [name for name in names if name not in done]
print(f"union={len(names)} settled={len(done)} todo={len(todo)}", flush=True)

lock = threading.Lock()
out_handle = open(OUT_PATH, "a", newline="")
writer = csv.writer(out_handle, delimiter="\t")
if not done:
    writer.writerow(["name", "smiles", "resolver"])
    out_handle.flush()

processed = resolved = transient_n = 0
start = time.time()
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    for name, (smiles, who, status) in zip(todo, pool.map(resolve, todo)):
        with lock:
            processed += 1
            if status == "transient":
                transient_n += 1
            else:
                # Only settled outcomes are persisted; transient ones are left for a rerun.
                writer.writerow([name, smiles, who])
                out_handle.flush()
                if status == "resolved":
                    resolved += 1
            if processed % 250 == 0:
                rate = processed / (time.time() - start)
                eta = (len(todo) - processed) / rate / 60 if rate else 0
                print(
                    f"{processed}/{len(todo)} | resolved={resolved} "
                    f"transient={transient_n} | {rate:.1f}/s ETA {eta:.0f}m",
                    flush=True,
                )

out_handle.close()
print(f"DONE processed={processed} resolved={resolved} transient={transient_n}", flush=True)
