"""Prepare inputs for the LLM RXC->RXNO crosswalk workflow.

Dedupes the 6,926 RXC classes to distinct reaction descriptions (merging
'cond:' condition variants), writes the RXNO vocabulary, and splits the distinct
names into batch files that workflow agents will Read.
"""
import json
import os
import re

WORK = "crosswalk_work"
BATCH = 120
os.makedirs(WORK, exist_ok=True)


def parse_obo(path, prefix):
    terms, cur = [], None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line == "[Term]":
            cur = {"id": None, "name": None, "syn": [], "obs": False}
            terms.append(cur)
        elif cur is not None:
            if line.startswith("id: "):
                cur["id"] = line[4:]
            elif line.startswith("name: "):
                cur["name"] = line[6:]
            elif line.startswith("synonym: "):
                q, = [line.find('"')]
                q2 = line.find('"', q + 1)
                if q >= 0 and q2 > q:
                    cur["syn"].append(line[q + 1:q2])
            elif line.startswith("is_obsolete: true"):
                cur["obs"] = True
        if line == "":
            cur = None
    return [t for t in terms if t["id"] and not t["obs"] and t["id"].startswith(prefix)]


# RXNO vocabulary file (id | name | synonyms)
rxno = parse_obo("rxno.obo", "RXNO")
with open(f"{WORK}/vocab.txt", "w") as fh:
    for t in sorted(rxno, key=lambda x: x["id"]):
        syn = "; ".join(t["syn"][:4])
        fh.write(f"{t['id']} | {t['name']}" + (f" | syn: {syn}" if syn else "") + "\n")
print(f"vocab.txt: {len(rxno)} RXNO terms")


def map_name(full):
    """Drop 'cond:' segments so condition variants share one reaction description."""
    segs = [s.strip() for s in (full or "").split("|")]
    segs = [s for s in segs if s and not re.match(r"(?i)^cond\s*:", s)]
    return " | ".join(segs)


rxc = json.load(open("rxc_classes.json"))
code2name, names = {}, {}
for c in rxc:
    nm = map_name(c["full"]) or c["code"]
    code2name[c["code"]] = nm
    names.setdefault(nm, len(names))
json.dump(code2name, open(f"{WORK}/code2name.json", "w"))
idx2name = {i: nm for nm, i in names.items()}
json.dump(idx2name, open(f"{WORK}/idx2name.json", "w"))

items = [{"i": i, "name": nm} for nm, i in names.items()]
nbatch = (len(items) + BATCH - 1) // BATCH
for b in range(nbatch):
    json.dump(items[b * BATCH:(b + 1) * BATCH], open(f"{WORK}/batch_{b:03d}.json", "w"))
print(f"distinct reaction descriptions: {len(items)} -> {nbatch} batches of {BATCH}")
print(f"work dir: {os.path.abspath(WORK)}")
