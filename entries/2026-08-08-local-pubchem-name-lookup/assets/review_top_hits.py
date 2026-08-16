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

"""Hand-review the highest-impact answers the local index returns.

The index is only worth having if its answers are right, and row-weighted coverage says
nothing about that: a single wrong answer on a frequent name writes a wrong structure
onto thousands of ORD rows. So the top hits by row count are judged one at a time.

"label" is the failure mode that matters here. PubChem's synonym table is
depositor-supplied, so it carries paper-local compound labels ("5u", "3A", "II") and
functional-class words ("imine", "thiol", "anhydride") that some depositor attached to a
specific structure. ORD's name-only field is full of exactly those strings used as
labels, so an exact match on one is a collision, not a resolution.

Usage: review_top_hits.py LOCAL_HITS TOP_N OUT.tsv
"""

import argparse
import csv
import pathlib

# name -> (verdict, why). "label" means the ORD name is a class/abbreviation/paper label
# and the returned structure is one arbitrary compound a depositor filed under it.
VERDICTS = {
    "hexanes": ("ok", "n-hexane for the isomer mixture; the 2026-07-11 dictionary made the same call"),
    "Hexanes": ("ok", "same"),
    "heptanes": ("ok", "n-heptane for the isomer mixture"),
    "SiO2": ("ok", "silica"),
    "cuprous iodide": ("ok", ""),
    "cuprous chloride": ("ok", ""),
    "cuprous cyanide": ("ok", ""),
    "cuprous bromide": ("ok", ""),
    "cuprous oxide": ("ok", ""),
    "cupric acetate": ("ok", ""),
    "NH4OAc": ("ok", ""),
    "NaH2PO4": ("ok", ""),
    "KHCO3": ("ok", ""),
    "NaIO4": ("ok", ""),
    "Na2S2O5": ("ok", ""),
    "Na2SO4.10H2O": ("ok", ""),
    "CaSO4": ("ok", ""),
    "CrO3": ("ok", ""),
    "FeCl3": ("ok", ""),
    "ferric chloride": ("ok", ""),
    "PCy3": ("ok", ""),
    "PtO2": ("ok", ""),
    "Pd(OAc)2": ("ok", ""),
    "[Rh(cod)2]BF4": ("ok", ""),
    "Mg": ("ok", ""),
    "Si": ("ok", ""),
    "reduced iron": ("ok", ""),
    "stannous chloride": ("ok", ""),
    "stannous chloride dihydrate": ("ok", ""),
    "stannic chloride": ("ok", ""),
    "mercuric chloride": ("ok", ""),
    "mercuric acetate": ("ok", ""),
    "mercuric oxide": ("ok", ""),
    "ceric ammonium nitrate": ("ok", ""),
    "N,N'-carbonyldiimidazole": ("ok", ""),
    "1,1-carbonyldiimidazole": ("ok", "CDI under a nonstandard spelling"),
    "N,N-dicyclohexylcarbodiimide": ("ok", "DCC"),
    "4A": ("label", "4A molecular sieves; returns a benzothiazine from some paper"),
    "3A": ("label", "3A molecular sieves; returns a rhodium phosphine complex"),
    "2B": ("label", "returns benzalkonium chloride"),
    "5u": ("label", "compound label from a paper"),
    "E1": ("label", "returns a peptide"),
    "II": ("label", "roman-numeral compound label; returns a dipeptide"),
    "IV": ("label", "roman-numeral compound label; returns a dipeptide"),
    "raw material": ("label", "returns histidine methyl ester hydrochloride"),
    "Boc": ("label", "protecting group; returns a peptide"),
    "BOC": ("label", "same"),
    "anhydride": ("label", "functional class; returns a nucleotide"),
    "acetal": ("label", "functional class; returns 1,1-diethoxyethane"),
    "dimethyl acetal": ("label", "functional class; returns 1,1-dimethoxyethane"),
    "diethyl ester": ("label", "functional class; returns diethyl phthalate"),
    "imine": ("label", "functional class; returns a macrocyclic Schiff base"),
    "epoxide": ("label", "functional class; returns a terpene epoxide"),
    "sulfonamide": ("label", "functional class; returns sulfanilamide"),
    "nitro": ("label", "functional group"),
    "thiol": ("label", "functional group; returns hydrogen sulfide"),
    "diazonium": ("label", "functional group"),
    "oxide": ("label", "returns the bare oxide dianion"),
    "peroxide": ("label", "returns hydrogen peroxide, which is a guess at what was meant"),
    "nylon": ("label", "polymer"),
}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("local_hits", type=pathlib.Path)
parser.add_argument("top_n", type=int)
parser.add_argument("out", type=pathlib.Path)
args = parser.parse_args()

with args.local_hits.open() as handle:
    hits = [row for row in csv.DictReader(handle, delimiter="\t") if row["smiles"]]
hits.sort(key=lambda row: -int(row["rows"]))
top = hits[: args.top_n]

missing = [row["name"] for row in top if row["name"] not in VERDICTS]
if missing:
    raise SystemExit(f"no verdict recorded for: {missing}")

with args.out.open("w", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t")
    writer.writerow(["rows", "name", "smiles", "verdict", "note"])
    for row in top:
        verdict, note = VERDICTS[row["name"]]
        writer.writerow([row["rows"], row["name"], row["smiles"], verdict, note])

for verdict in ("ok", "label"):
    chosen = [row for row in top if VERDICTS[row["name"]][0] == verdict]
    rows = sum(int(row["rows"]) for row in chosen)
    print(
        f"{verdict:<6} {len(chosen):>3}/{len(top)} names  {rows:>7,} rows "
        f"({rows / sum(int(r['rows']) for r in top):.1%} of the reviewed rows)"
    )
print(f"reviewed rows {sum(int(r['rows']) for r in top):,} of {sum(int(r['rows']) for r in hits):,} hit rows")
