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

"""Capture side-by-side example outputs from both classifiers.

Usage: examples.py out.json
"""
import json
import sys

from reactionclassifier import ReactionClassifier
from rxn_insight.reaction import Reaction
from rxnmapper import RXNMapper

EXAMPLES = [
    ("Amide coupling (acid + amine)", "CC(=O)O.NCc1ccccc1>>CC(=O)NCc1ccccc1"),
    ("Suzuki coupling", "OB(O)c1ccccc1.Brc1ccccc1>>c1ccc(-c2ccccc2)cc1"),
    ("SNAr / N-arylation", "OCC1CNC1.COc1cnc(Cl)cc1>>COc1cnc(N2CC(CO)C2)cc1"),
    ("Nitro reduction to aniline", "O=[N+]([O-])c1ccccc1>>Nc1ccccc1"),
    ("Boc protection of amine",
     "CC(C)(C)OC(=O)OC(=O)OC(C)(C)C.NCc1ccccc1>>CC(C)(C)OC(=O)NCc1ccccc1"),
    ("Ester saponification", "CCOC(=O)c1ccccc1>>O=C(O)c1ccccc1"),
    # Real ORD reactions from the sample (line indices held out below):
    ("ORD sample: SNAr amination",
     "N#Cc1c(Cl)nc(Cl)nc1Cl.CCN>>CCNc1nc(Cl)c(C#N)c(Cl)n1"),
    ("ORD sample: barbituric condensation",
     "O=C1CC(=O)NC(=O)N1.NC(N)=O>>NC(=O)c1c(O)nc(O)nc1O"),
]

clf = ReactionClassifier()
mapper = RXNMapper()

rows = []
for label, smi in EXAMPLES:
    r = clf.classify(smi)
    try:
        info = Reaction(smi, rxn_mapper=mapper).get_reaction_info()
        ri_class, ri_name = info.get("CLASS"), info.get("NAME")
    except Exception as e:
        ri_class, ri_name = f"ERROR:{type(e).__name__}", None
    rows.append({
        "label": label,
        "smiles": smi,
        "rxc_confirmed_code": r.reaction_code,
        "rxc_confirmed_name": r.reaction_name,
        "rxc_neural_code": r.neural_code,
        "rxc_neural_name": r.neural_name,
        "rxc_confidence": r.confidence,
        "ri_class": ri_class,
        "ri_name": ri_name,
    })
    print(f"\n### {label}\n  {smi}")
    print(f"  RXC confirmed: {r.reaction_code}  {r.reaction_name}")
    print(f"  RXC neural   : {r.neural_code}  {r.neural_name}  (conf {r.confidence})")
    print(f"  Rxn-INSIGHT  : {ri_class}  |  {ri_name}")

with open(sys.argv[1], "w") as fh:
    json.dump(rows, fh, indent=2)
