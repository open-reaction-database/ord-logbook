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

"""Classify the ORD sample with SynCat using the calibrated index->code map.

Separate process from calibration so peak RSS reflects the classification
workload only.

Usage: syncat_classify.py reactions_2part.smi out.json
"""
import json
import os
import resource
import sys
import time

import torch

sys.path.insert(0, "SynCat/src")
from predict import predict  # noqa: E402

MP = os.path.abspath("SynCat/Data/model/") + "/"

EXAMPLES = [
    ("Amide coupling", "CC(=O)O.NCc1ccccc1>>CC(=O)NCc1ccccc1"),
    ("Suzuki coupling", "OB(O)c1ccccc1.Brc1ccccc1>>c1ccc(-c2ccccc2)cc1"),
    ("SNAr / N-arylation", "OCC1CNC1.COc1cnc(Cl)cc1>>COc1cnc(N2CC(CO)C2)cc1"),
    ("Nitro reduction", "O=[N+]([O-])c1ccccc1>>Nc1ccccc1"),
    ("Boc protection", "CC(C)(C)OC(=O)OC(=O)OC(C)(C)C.NCc1ccccc1>>CC(C)(C)OC(=O)NCc1ccccc1"),
    ("Ester saponification", "CCOC(=O)c1ccccc1>>O=C(O)c1ccccc1"),
    ("ORD SNAr amination", "N#Cc1c(Cl)nc(Cl)nc1Cl.CCN>>CCNc1nc(Cl)c(C#N)c(Cl)n1"),
    ("ORD barbituric condensation", "O=C1CC(=O)NC(=O)N1.NC(N)=O>>NC(=O)c1c(O)nc(O)nc1O"),
]


def peak_rss_mb():
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024


def run(rsmis):
    res = predict(rsmis, model_path=MP, model_name="model_schneider", device=0)
    out = []
    for b in res:
        out.extend(torch.as_tensor(b[0]).argmax(-1).tolist())
    return out


cal = json.load(open("syncat_index2code.json"))
index2code = {int(k): v for k, v in cal["index2code"].items()}
names = json.load(open("rxnfp_data/rxnclass2name.json"))


def code_name(i):
    c = index2code.get(i)
    return c, names.get(c, c)


rxns = [ln.strip() for ln in open(sys.argv[1]) if ln.strip()]
run(rxns[:16])  # warm up

t0 = time.perf_counter()
idxs = run(rxns)
steady = time.perf_counter() - t0
labels = [code_name(i)[0] for i in idxs]

examples = []
for (label, smi), i in zip(EXAMPLES, run([s for _, s in EXAMPLES])):
    c, nm = code_name(i)
    examples.append({"label": label, "smiles": smi, "code": c, "name": nm})
    print(f"  {label:28} -> {c}  {nm}")

summary = {
    "mode": "syncat",
    "n": len(rxns),
    "calibration_test_accuracy": round(cal["cal_acc"], 4),
    "steady_seconds": round(steady, 2),
    "throughput_rxn_per_s": round(len(rxns) / steady, 2),
    "note": "end-to-end (RDKit featurize + batched GNN, batch=8) incl. one model load",
    "peak_rss_mb": round(peak_rss_mb(), 1),
}
json.dump({"summary": summary, "labels": labels, "examples": examples}, open(sys.argv[2], "w"))
print(json.dumps(summary, indent=2))
