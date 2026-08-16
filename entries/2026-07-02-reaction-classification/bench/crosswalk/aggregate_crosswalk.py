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

"""Aggregate the LLM RXC->RXNO crosswalk outputs and report coverage.

Reads crosswalk_work/out_*.json, joins to RXC codes, and reports coverage vs the
string-match baseline (specificity, RXNO recall, ORD-weighted, by superclass).
"""
import glob
import json
from collections import Counter, defaultdict

WORK = "crosswalk_work"

# valid RXNO ids + names + a set of broad "umbrella" nodes for specificity scoring
rxno_name, umbrella = {}, set()
UMBRELLA_NAMES = {
    "carbon-carbon coupling reaction", "molecular skeleton joining reaction",
    "heterocycle synthesis", "n-acylation to amide", "n-acylation to urea",
    "o-acylation to ester", "heteroaryl n-alkylation", "amide n-alkylation",
    "reductive amination", "ring breaking", "ring formation reaction step",
    "coupling reaction", "acylation reaction", "n-alkylation", "o-alkylation",
    "functional group interconversion", "oxidation reaction step", "reduction reaction step",
}
cur = None
for line in open("rxno.obo", encoding="utf-8"):
    if line.startswith("id: RXNO:"):
        cur = line[4:].strip()
    elif line.startswith("name: ") and cur:
        nm = line[6:].strip()
        rxno_name[cur] = nm
        if nm.lower() in UMBRELLA_NAMES:
            umbrella.add(cur)
        cur = None

idx2name = {int(k): v for k, v in json.load(open(f"{WORK}/idx2name.json")).items()}
code2name = json.load(open(f"{WORK}/code2name.json"))
name2idx = {v: k for k, v in idx2name.items()}

# load agent outputs
idx2rxno, idx2conf = {}, {}
got_batches, bad_ids = set(), 0
for f in sorted(glob.glob(f"{WORK}/out_*.json")):
    got_batches.add(f)
    try:
        rows = json.load(open(f))
    except Exception as e:
        print(f"  !! bad JSON in {f}: {e}")
        continue
    for r in rows:
        rid = r.get("rxno_id")
        if rid is not None and rid not in rxno_name:
            bad_ids += 1
            rid = None
        idx2rxno[int(r["i"])] = rid
        idx2conf[int(r["i"])] = r.get("confidence", "?")

n_expected = len(idx2name)
missing_idx = [i for i in idx2name if i not in idx2rxno]
print(f"batches with output: {len(got_batches)}/47   descriptions mapped: {len(idx2rxno)}/{n_expected}")
if missing_idx:
    print(f"  !! missing {len(missing_idx)} descriptions (incomplete batches)")
if bad_ids:
    print(f"  !! {bad_ids} invalid ids coerced to null")

# project to all RXC codes
code2rxno = {code: idx2rxno.get(name2idx.get(nm)) for code, nm in code2name.items()}
code2conf = {code: idx2conf.get(name2idx.get(nm)) for code, nm in code2name.items()}
json.dump({c: {"rxno": code2rxno[c], "rxno_name": rxno_name.get(code2rxno[c]),
               "conf": code2conf[c]} for c in code2rxno},
          open("rxc_rxno_crosswalk_llm.json", "w"))

n = len(code2rxno)
mapped = [c for c, r in code2rxno.items() if r]
specific = [c for c in mapped if code2rxno[c] not in umbrella]
hi = [c for c in mapped if code2conf[c] == "high"]
print(f"\nRXC classes: {n}")
print(f"  mapped to an RXNO id: {len(mapped)} ({100*len(mapped)/n:.0f}%)")
print(f"  of which SPECIFIC (non-umbrella): {len(specific)} ({100*len(specific)/n:.0f}% of all)")
print(f"  high-confidence: {len(hi)} ({100*len(hi)/n:.0f}%)")
print(f"  RXNO recall: {len({code2rxno[c] for c in mapped})}/653 terms")
print(f"  distinct SPECIFIC RXNO terms hit: {len({code2rxno[c] for c in specific})}")

# ORD-weighted
res = json.load(open("rxc_result.json"))
conf_labels = [l for l in res["labels"] if l and not l.startswith("~")]
wm = sum(1 for c in conf_labels if code2rxno.get(c))
ws = sum(1 for c in conf_labels if code2rxno.get(c) and code2rxno[c] not in umbrella)
print(f"\nORD-weighted (over {len(conf_labels)} confirmed labels):")
print(f"  any RXNO id: {100*wm/len(conf_labels):.0f}%   specific RXNO id: {100*ws/len(conf_labels):.0f}%")

# by superclass
by_sc = defaultdict(lambda: [0, 0])
for c, r in code2rxno.items():
    by_sc[c.split(".")[0]][0] += 1
    if r:
        by_sc[c.split(".")[0]][1] += 1
print("\nBy RXC superclass (mapped / total):")
for sc in sorted(by_sc, key=int):
    tot, m = by_sc[sc][0], by_sc[sc][1]
    print(f"  {sc}: {m:4}/{tot:4} ({100*m/tot:.0f}%)")

# vs string-match baseline
try:
    sm = json.load(open("rxc_rxno_crosswalk.json"))
    sm_hi = {c for c, v in sm.items() if v["tier"] == "high" and v["rxno"] not in umbrella}
    llm_hi = set(specific)
    print(f"\nvs string-match: specific-map by string {len(sm_hi)}, by LLM {len(llm_hi)}, "
          f"LLM-only gains {len(llm_hi - sm_hi)}")
except Exception:
    pass

print("\n--- sample high-confidence specific mappings ---")
shown = 0
for c in sorted(mapped):
    if code2conf[c] == "high" and code2rxno[c] not in umbrella and shown < 15:
        print(f"  {c:14} {code2name[c][:46]:46} -> {code2rxno[c]} {rxno_name[code2rxno[c]]}")
        shown += 1
