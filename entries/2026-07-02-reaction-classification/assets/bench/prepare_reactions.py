"""Sample the benchmark reaction set from a local ord-data checkout.

Deterministic (fixed seed): walks datasets, extracts reaction SMILES, strips
atom maps, and writes both the 3-part form (used by ReactionClassifier and
Rxn-INSIGHT) and the 2-part agents-on-left form (used by rxnfp and SynCat, to
match the Schneider-50k training distribution).

Run in an env with ord_schema + rdkit importable:
    python prepare_reactions.py /path/to/ord-data reactions_unmapped.smi reactions_2part.smi
"""
import glob
import random
import sys

from ord_schema import message_helpers as mh
from ord_schema.proto import dataset_pb2
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

TARGET = 3000
PER_DATASET_CAP = 200


def strip_maps(component: str):
    """Canonicalize each '.'-joined fragment with atom-map numbers removed."""
    outs = []
    for smi in component.split("."):
        if not smi:
            continue
        m = Chem.MolFromSmiles(smi)
        if m is None:
            return None
        for a in m.GetAtoms():
            a.SetAtomMapNum(0)
        outs.append(Chem.MolToSmiles(m))
    return ".".join(outs)


def main():
    ord_data, out_unmapped, out_2part = sys.argv[1], sys.argv[2], sys.argv[3]

    paths = sorted(glob.glob(f"{ord_data}/data/*/*.pb.gz"))
    random.Random(0).shuffle(paths)

    seen, smiles = set(), []
    for p in paths:
        if len(smiles) >= TARGET:
            break
        try:
            ds = mh.load_message(p, dataset_pb2.Dataset)
        except Exception:
            continue
        n_this = 0
        for rxn in ds.reactions:
            if len(smiles) >= TARGET or n_this >= PER_DATASET_CAP:
                break
            try:
                rs = mh.get_reaction_smiles(
                    rxn, generate_if_missing=True, allow_incomplete=True,
                    validate=False, canonical=True,
                )
            except Exception:
                rs = None
            if not rs or ">" not in rs:
                continue
            if not rs.split(">")[0] or not rs.split(">")[-1] or rs in seen:
                continue
            seen.add(rs)
            smiles.append(rs)
            n_this += 1

    # Strip atom maps (both classifiers compare unmapped canonical products) and
    # emit the two input forms.
    n = 0
    with open(out_unmapped, "w") as fu, open(out_2part, "w") as f2:
        for rs in smiles:
            parts = rs.split(">")
            if len(parts) == 2:
                left, mid, right = parts[0], "", parts[1]
            elif len(parts) == 3:
                left, mid, right = parts
            else:
                continue
            lo = strip_maps(left)
            ro = strip_maps(right)
            mo = strip_maps(mid) if mid else ""
            if not lo or not ro:
                continue
            fu.write(f"{lo}>{mo}>{ro}\n")
            left_full = f"{lo}.{mo}" if mo else lo
            f2.write(f"{left_full}>>{ro}\n")
            n += 1
    print(f"wrote {n} reactions to {out_unmapped} and {out_2part}")


if __name__ == "__main__":
    main()
