"""Benchmark rxnfp (bert_ft fingerprint + logistic head) on the 50 NameRxn classes.

Trains a logistic-regression head on the bundled Schneider-50k fingerprints,
then times per-reaction (fingerprint + predict) on the ORD sample.

Usage: rxnfp_bench.py reactions_2part.smi out.json
"""
import csv
import json
import resource
import sys
import time

import numpy as np
from sklearn.linear_model import LogisticRegression

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


def pct(v, q):
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0.0


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]

    # --- train the 50-class head on bundled Schneider fingerprints ---
    z = np.load("rxnfp_data/fps_ft.npz")
    fps = z[list(z.keys())[0]]
    codes, splits = [], []
    with open("rxnfp_data/schneider50k.tsv") as f:
        r = csv.reader(f, delimiter="\t")
        h = next(r)
        ix = {n: i for i, n in enumerate(h)}
        for row in r:
            codes.append(row[ix["rxn_class"]])
            splits.append(row[ix["split"]])
    codes = np.array(codes)
    splits = np.array(splits)
    assert len(codes) == len(fps), (len(codes), len(fps))
    tr, te = splits == "train", splits == "test"
    clf = LogisticRegression(max_iter=2000, n_jobs=-1)
    clf.fit(fps[tr], codes[tr])
    head_acc = float(clf.score(fps[te], codes[te]))
    print(f"rxnfp+logreg Schneider test accuracy: {head_acc:.4f} "
          f"(train {tr.sum()}, test {te.sum()}, fp dim {fps.shape[1]})")

    names = json.load(open("rxnfp_data/rxnclass2name.json"))

    # --- load the rxnfp bert_ft fingerprint model ---
    t0 = time.perf_counter()
    from rxnfp.transformer_fingerprints import (
        RXNBERTFingerprintGenerator,
        get_default_model_and_tokenizer,
    )
    model, tok = get_default_model_and_tokenizer()
    gen = RXNBERTFingerprintGenerator(model, tok)
    load_s = time.perf_counter() - t0

    def classify(rxn):
        fp = np.asarray(gen.convert(rxn), dtype=np.float32).reshape(1, -1)
        code = clf.predict(fp)[0]
        return code, names.get(code, code)

    with open(in_path) as f:
        rxns = [ln.strip() for ln in f if ln.strip()]

    classify(rxns[0])  # warm up

    labels, lat = [], []
    t_start = time.perf_counter()
    for smi in rxns:
        t = time.perf_counter()
        try:
            code, _ = classify(smi)
        except Exception:
            code = None
        lat.append(time.perf_counter() - t)
        labels.append(code)
    steady = time.perf_counter() - t_start
    lat.sort()
    n = len(rxns)

    examples = []
    for label, smi in EXAMPLES:
        try:
            code, name = classify(smi)
        except Exception as e:
            code, name = f"ERROR:{type(e).__name__}", None
        examples.append({"label": label, "smiles": smi, "code": code, "name": name})
        print(f"  {label:28} -> {code}  {name}")

    summary = {
        "mode": "rxnfp",
        "n": n,
        "head_test_accuracy": round(head_acc, 4),
        "load_seconds": round(load_s, 2),
        "steady_seconds": round(steady, 2),
        "throughput_rxn_per_s": round(n / steady, 2),
        "latency_ms_median": round(1000 * pct(lat, 0.5), 2),
        "latency_ms_p90": round(1000 * pct(lat, 0.9), 2),
        "peak_rss_mb": round(peak_rss_mb(), 1),
    }
    json.dump({"summary": summary, "labels": labels, "examples": examples}, open(out_path, "w"))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
