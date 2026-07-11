# Benchmark assets

Scripts behind the "Hands-on benchmark" section of the entry: four reaction
classifiers timed on the same 1,572 ORD reactions (single CPU process, isolated
venv, dev Mac, 2026-07-02). Kept for reproducibility; paths are relative to a
scratch working directory laid out as described below.

## Layout expected at run time

```text
work/
  bench-venv/                 # the isolated venv
  reactions_unmapped.smi      # 3-part form  (ReactionClassifier, Rxn-INSIGHT)
  reactions_2part.smi         # 2-part form  (rxnfp, SynCat)
  rxnfp_data/                 # fps_ft.npz, schneider50k.tsv, rxnclass2*.json
  SynCat/                     # git clone of phuocchung123/SynCat
  <these scripts>
```

## Setup

```bash
python -m venv bench-venv
# ReactionClassifier (pulls rdkit/torch/numpy):
./bench-venv/bin/pip install reactionclassifier
# Rxn-INSIGHT (the ORD-pinned fork) + rxnmapper:
./bench-venv/bin/pip install \
  "rxn-insight @ git+https://github.com/skearnes/Rxn-INSIGHT.git@eb71946997e81801ba56c66c9a564263743c7eee" \
  rxnmapper setuptools
# rxnfp (deps are ancient hard-pins; install without them — torch/transformers already present):
./bench-venv/bin/pip install --no-deps rxnfp
./bench-venv/bin/pip install scikit-learn
# SynCat (GINE GNN; torch_geometric only, no torch-scatter build needed):
./bench-venv/bin/pip install --no-deps torch_geometric==2.6.0
git clone --depth 1 https://github.com/phuocchung123/SynCat.git

# rxnfp data files (bundled fingerprints + Schneider-50k labels + name maps):
mkdir -p rxnfp_data
for f in fps_ft.npz schneider50k.tsv rxnclass2name.json rxnclass2id.json; do
  curl -sSL "https://raw.githubusercontent.com/rxn4chemistry/rxnfp/master/data/$f" -o "rxnfp_data/$f"
done
```

## Reproduce

```bash
# 1. Sample the reaction set (deterministic; needs ord_schema + a local ord-data).
python prepare_reactions.py /path/to/ord-data reactions_unmapped.smi reactions_2part.smi

# 2. ReactionClassifier and Rxn-INSIGHT (throughput / coverage / memory).
./bench-venv/bin/python bench.py rxc reactions_unmapped.smi rxc_result.json
./bench-venv/bin/python bench.py ri  reactions_unmapped.smi ri_result.json
./bench-venv/bin/python examples.py examples_result.json          # their side-by-side outputs

# 3. rxnfp: train the 50-class head on bundled fingerprints, then benchmark.
./bench-venv/bin/python rxnfp_bench.py reactions_2part.smi rxnfp_result.json

# 4. SynCat: calibrate output-index -> NameRxn code, then benchmark.
./bench-venv/bin/python syncat_calibrate.py 6000
./bench-venv/bin/python syncat_classify.py reactions_2part.smi syncat_result.json
```

## Headline results

| Classifier | Throughput | Peak RSS | Label space | Accuracy |
| --- | --- | --- | --- | --- |
| ReactionClassifier | 169.8 rxn/s | 1,380 MB | 6,962 own | 58.7% confirmed (ORD) |
| Rxn-INSIGHT | 8.6 rxn/s | 461 MB | ~528 named | 51.4% named (ORD) |
| rxnfp + logistic head | 186.1 rxn/s | 622 MB | 50 NameRxn | 0.994 (Schneider test) |
| SynCat | 112.1 rxn/s | 367 MB | 50 NameRxn | 0.976 / 0.988 (Schneider) |

Caveats: single CPU process on one machine (relative numbers, not a leaderboard);
per-reaction timing for all but SynCat, which batches at 8; the ORD accuracy
(specific-label rate) and the Schneider accuracy are different metrics and not
directly comparable.
