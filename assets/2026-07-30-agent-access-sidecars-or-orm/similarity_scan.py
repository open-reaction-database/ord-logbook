"""Similarity-search cost and structure-sidecar sizing, no index."""
import json, time
import numpy as np
from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator, rdmolops
from ord_schema.logging import silence_rdkit_logs

silence_rdkit_logs()
N = 100_000
path = "/private/tmp/claude-501/-Users-skearnes-ord-ord-data/4f032fb8-3e1a-46d7-b68c-f7be4a5d5550/scratchpad/uniq_smiles.txt"
smiles = []
with open(path) as f:
    for i, line in enumerate(f):
        if i >= N: break
        smiles.append(line.rstrip("\n"))
mols = [m for m in (Chem.MolFromSmiles(s) for s in smiles) if m is not None]

gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
t0 = time.time()
morgan = np.zeros((len(mols), 2048 // 8), dtype=np.uint8)
for i, m in enumerate(mols):
    morgan[i] = np.frombuffer(gen.GetFingerprintAsNumPy(m).astype(np.uint8).tobytes(), dtype=np.uint8).reshape(-1, 8).dot(1 << np.arange(8)[::-1]).astype(np.uint8) if False else np.packbits(gen.GetFingerprintAsNumPy(m))
morgan_build_s = time.time() - t0

q = gen.GetFingerprintAsNumPy(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
qp = np.packbits(q)
popcount = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(1).astype(np.uint16)
t0 = time.time()
inter = popcount[np.bitwise_and(morgan, qp)].sum(1)
union = popcount[np.bitwise_or(morgan, qp)].sum(1)
tan = inter / np.maximum(union, 1)
n_hits = int((tan >= 0.5).sum())
tanimoto_s = time.time() - t0

TOTAL = 1_432_318
scale = TOTAL / len(mols)
print(json.dumps({
    "sampled": len(mols),
    "morgan_build_seconds": round(morgan_build_s, 1),
    "tanimoto_scan_seconds": round(tanimoto_s, 3),
    "hits_at_0.5": n_hits,
    "projected_full_corpus": {
        "morgan_build_minutes": round(morgan_build_s * scale / 60, 1),
        "tanimoto_scan_seconds": round(tanimoto_s * scale, 2),
    },
    "structure_sidecar_mb": {
        f"{bits}_bit_two_fps": round(TOTAL * (bits // 8) * 2 / 1e6, 1)
        for bits in (512, 1024, 2048)
    },
}, indent=2))
