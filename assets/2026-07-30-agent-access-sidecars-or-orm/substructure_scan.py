"""Cost of substructure search over the corpus's distinct structures, no GiST index.

Mirrors what the RDKit cartridge does: a pattern-fingerprint screen, then an exact
substructure verification on the survivors.
"""
import json, time
import numpy as np
from rdkit import Chem
from rdkit.Chem import rdmolops
from ord_schema.logging import silence_rdkit_logs

silence_rdkit_logs()
N = 100_000
NBITS = 2048
path = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/uniq_smiles.txt"
smiles = []
with open(path) as f:
    for i, line in enumerate(f):
        if i >= N:
            break
        smiles.append(line.rstrip("\n"))

t0 = time.time()
mols = [Chem.MolFromSmiles(s) for s in smiles]
mols = [m for m in mols if m is not None]
parse_s = time.time() - t0

t0 = time.time()
packed = np.zeros((len(mols), NBITS // 8), dtype=np.uint8)
for i, m in enumerate(mols):
    fp = rdmolops.PatternFingerprint(m, fpSize=NBITS)
    packed[i] = np.frombuffer(bytes(fp.ToBitString().encode()), dtype=np.uint8)[:0] if False else np.packbits(np.frombuffer(fp.ToBitString().encode(), dtype=np.uint8) - ord('0'))
fp_s = time.time() - t0

PATTERNS = {"carboxylic acid": "C(=O)O", "pyridine": "c1ccncc1", "boronic acid": "B(O)O", "aryl halide": "c[F,Cl,Br,I]"}
results = {}
for name, patt in PATTERNS.items():
    q = Chem.MolFromSmiles(patt) or Chem.MolFromSmarts(patt)
    qfp = np.packbits(np.frombuffer(rdmolops.PatternFingerprint(q, fpSize=NBITS).ToBitString().encode(), dtype=np.uint8) - ord('0'))
    t0 = time.time()
    # Screen: keep rows whose bits are a superset of the query's bits.
    keep = ~np.any(np.bitwise_and(qfp, ~packed), axis=1)
    screen_s = time.time() - t0
    cand = np.flatnonzero(keep)
    t0 = time.time()
    hits = sum(1 for i in cand if mols[i].HasSubstructMatch(q))
    verify_s = time.time() - t0
    results[name] = {"candidates": int(cand.size), "hits": hits,
                     "screen_ms": round(screen_s * 1000, 1), "verify_s": round(verify_s, 2),
                     "screen_retained_pct": round(100 * cand.size / len(mols), 1)}

print(json.dumps({
    "sampled_mols": len(mols),
    "parse_seconds": round(parse_s, 1),
    "pattern_fp_seconds": round(fp_s, 1),
    "fp_bytes_per_mol": NBITS // 8,
    "queries": results,
}, indent=2))
