"""Calibrate SynCat output-index -> NameRxn-code map on labeled Schneider test.

Runs in its own process so its featurization memory doesn't pollute the
classification benchmark. Writes syncat_index2code.json.

Usage: syncat_calibrate.py [cap]
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict

import torch

sys.path.insert(0, "SynCat/src")
from predict import predict  # noqa: E402

MP = os.path.abspath("SynCat/Data/model/") + "/"
CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 6000


def run(rsmis):
    res = predict(rsmis, model_path=MP, model_name="model_schneider", device=0)
    out = []
    for b in res:
        out.extend(torch.as_tensor(b[0]).argmax(-1).tolist())
    return out


test_rxn, test_code = [], []
with open("rxnfp_data/schneider50k.tsv") as f:
    r = csv.reader(f, delimiter="\t")
    h = next(r)
    ix = {n: i for i, n in enumerate(h)}
    for row in r:
        if row[ix["split"]] == "test":
            test_rxn.append(row[ix["rxn"]])
            test_code.append(row[ix["rxn_class"]])

if CAP and len(test_rxn) > CAP:
    step = len(test_rxn) // CAP
    test_rxn, test_code = test_rxn[::step][:CAP], test_code[::step][:CAP]

idx = run(test_rxn)
buckets = defaultdict(Counter)
for i, c in zip(idx, test_code):
    buckets[i][c] += 1
index2code = {str(i): cnt.most_common(1)[0][0] for i, cnt in buckets.items()}
correct = sum(1 for i, c in zip(idx, test_code) if index2code.get(str(i)) == c)
acc = correct / len(test_code)
json.dump({"index2code": index2code, "cal_acc": acc, "n": len(test_code)},
          open("syncat_index2code.json", "w"))
print(f"SynCat calibration: acc={acc:.4f} on n={len(test_code)}, "
      f"mapped {len(index2code)}/50 indices")
