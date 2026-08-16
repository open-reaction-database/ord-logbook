"""Scope the ReactionClassifier -> RXNO crosswalk (automated first pass).

For each of the 6,926 RXC operational classes, find the best RXNO term by
name/synonym matching, bucket into confidence tiers, and report coverage
(overall, RXNO recall, and weighted by ORD-benchmark frequency). MOP is checked
as a fallback to separate "generic transform -> MOP" from "truly unmapped".
"""
import json
import re
from collections import Counter, defaultdict

# generic chemistry words that must NOT be treated as eponyms / distinctive
GENERIC = set("""reaction reactions step synthesis coupling addition reduction oxidation
substitution rearrangement condensation cyclization cycloaddition formation cleavage
hydrolysis esterification amidation acylation alkylation arylation halogenation bromination
chlorination iodination fluorination nitration sulfonation amination protection deprotection
type acid acids amine amines amino ester esters ether ethers alcohol alcohols aldehyde
aldehydes ketone ketones nitro nitrile halide halides aryl alkyl vinyl group groups bond
bonds carbon carbonyl hydroxy hydroxyl primary secondary tertiary with from into via using
and or the a an of to at as by classic""".split())
STOP = set("the a an of to with and or for in into from by as at via using -> to".split())


def norm(s):
    s = (s or "").lower().replace("->", " ").replace("→", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def content_toks(s):
    return {t for t in norm(s).split() if t not in STOP and len(t) > 1}


def parse_obo(path, prefix):
    terms = []
    cur = None
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
                q = line.find('"')
                q2 = line.find('"', q + 1)
                if q >= 0 and q2 > q:
                    cur["syn"].append(line[q + 1:q2])
            elif line.startswith("is_obsolete: true"):
                cur["obs"] = True
        if line == "":
            cur = None
    return [t for t in terms if t["id"] and not t["obs"] and t["id"].startswith(prefix)]


def build_index(terms):
    """phrases: {normalized multiword phrase -> id}; eponyms: {token -> id}."""
    phrases, eponyms, token_index = {}, {}, []
    for t in terms:
        strings = [t["name"]] + t["syn"]
        for s in strings:
            n = norm(s)
            if len(n.split()) >= 2:
                phrases.setdefault(n, t["id"])
            for w in (s or "").split():
                wl = re.sub(r"[^A-Za-z-]", "", w)
                if (wl and wl[0].isupper() and not wl.isupper()
                        and len(wl) >= 4 and wl.lower() not in GENERIC):
                    eponyms.setdefault(wl.lower(), t["id"])
        # token set of the primary label for subset matching
        ct = content_toks(t["name"]) - GENERIC
        if len(ct) >= 2:
            token_index.append((ct, t["id"], t["name"]))
    return phrases, eponyms, token_index


def match(cand_text, cand_toks, phrases, eponyms, token_index, id2name):
    # High: contiguous multiword RXNO phrase in the RXC text
    for ph, tid in phrases.items():
        if ph in cand_text:
            return "high", tid, f"phrase:'{ph}'"
    # High: distinctive eponym token present
    for ep, tid in eponyms.items():
        if ep in cand_toks:
            return "high", tid, f"eponym:'{ep}'"
    # Medium: all content tokens of an RXNO label are a subset of the RXC tokens
    best = None
    for ct, tid, name in token_index:
        if ct <= cand_toks:
            score = len(ct)
            if best is None or score > best[0]:
                best = (score, tid, name)
    if best:
        return "medium", best[1], f"token-subset:'{best[2]}'"
    return "none", None, ""


rxno = parse_obo("rxno.obo", "RXNO")
mop = parse_obo("mop.obo", "MOP")
rxno_id2name = {t["id"]: t["name"] for t in rxno}
r_phrases, r_epon, r_tokens = build_index(rxno)
m_phrases, m_epon, m_tokens = build_index(mop)

rxc = json.load(open("rxc_classes.json"))
crosswalk = {}
for c in rxc:
    text = norm(" ".join(s for s in c["segs"] + [c["full"]] if s))
    ctoks = content_toks(" ".join(s for s in c["segs"] if s))
    tier, tid, ev = match(text, ctoks, r_phrases, r_epon, r_tokens, rxno_id2name)
    entry = {"tier": tier, "rxno": tid, "rxno_name": rxno_id2name.get(tid), "ev": ev}
    if tier == "none":
        mt, mid, mev = match(text, ctoks, m_phrases, m_epon, m_tokens, {})
        if mt != "none":
            entry["mop"] = mid
    crosswalk[c["code"]] = entry
json.dump(crosswalk, open("rxc_rxno_crosswalk.json", "w"))

# ---- report ----
tiers = Counter(v["tier"] for v in crosswalk.values())
n = len(crosswalk)
print(f"RXC operational classes: {n}")
print("Automated tier (of all classes):")
for t in ["high", "medium", "none"]:
    print(f"  {t:7}: {tiers[t]:5}  ({100*tiers[t]/n:.1f}%)")
mop_only = sum(1 for v in crosswalk.values() if v["tier"] == "none" and v.get("mop"))
print(f"  of 'none': {mop_only} match MOP (generic), {tiers['none']-mop_only} truly unmapped")
rxno_hit = {v["rxno"] for v in crosswalk.values() if v["rxno"]}
print(f"RXNO recall: {len(rxno_hit)}/653 native terms reached")

# superclass breakdown
by_sc = defaultdict(Counter)
for code, v in crosswalk.items():
    by_sc[code.split('.')[0]][v["tier"]] += 1
print("\nBy RXC superclass (high+medium mapped / total):")
for sc in sorted(by_sc, key=int):
    c = by_sc[sc]
    tot = sum(c.values())
    print(f"  {sc}: {c['high']+c['medium']:4}/{tot:4} mapped  ({100*(c['high']+c['medium'])/tot:.0f}%)")

# ORD-weighted coverage (confirmed benchmark labels)
res = json.load(open("rxc_result.json"))
conf = [l for l in res["labels"] if l and not l.startswith("~")]
wt = Counter(crosswalk.get(code, {}).get("tier", "none") for code in conf)
print(f"\nORD-weighted (over {len(conf)} confirmed benchmark labels):")
for t in ["high", "medium", "none"]:
    print(f"  {t:7}: {100*wt[t]/len(conf):.1f}%")

high_rxno = {v["rxno"] for v in crosswalk.values() if v["tier"] == "high"}
print(f"\nDistinct RXNO ids among HIGH matches: {len(high_rxno)}")
unmapped_named = sum(1 for code, v in crosswalk.items()
                     if v["tier"] == "none" and not v.get("mop") and code.split(".")[0] in "1234")
print(f"Truly-unmapped classes in named-rich superclasses 1-4 (recall headroom): {unmapped_named}")

print("\n--- sample HIGH matches ---")
shown = 0
for c in rxc:
    v = crosswalk[c["code"]]
    if v["tier"] == "high" and shown < 12:
        print(f"  {c['code']:14} {(c['leaf'] or c['full'] or '')[:42]:42} -> {v['rxno']} {v['rxno_name']}  [{v['ev']}]")
        shown += 1
print("--- sample MEDIUM matches ---")
shown = 0
for c in rxc:
    v = crosswalk[c["code"]]
    if v["tier"] == "medium" and shown < 8:
        print(f"  {c['code']:14} {(c['leaf'] or c['full'] or '')[:42]:42} -> {v['rxno']} {v['rxno_name']}  [{v['ev']}]")
        shown += 1
print("--- sample NONE (truly unmapped, no MOP) ---")
shown = 0
for c in rxc:
    v = crosswalk[c["code"]]
    if v["tier"] == "none" and not v.get("mop") and shown < 8:
        print(f"  {c['code']:14} {(c['leaf'] or c['full'] or c['code'])[:50]}")
        shown += 1
