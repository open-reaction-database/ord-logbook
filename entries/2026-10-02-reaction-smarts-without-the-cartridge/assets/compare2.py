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

"""Compares four readings of a reaction SMARTS over the sample.

cartridge   RDKit's hasReactionSubstructMatch, as the cartridge runs it: any one template
            per side, after a template-count check, on the reaction SMILES.
strict      every template matches some molecule on its side of the reaction SMILES,
            after the cartridge's move of mostly-unmapped reactants to agents.
decomp      every reactant template matches some input component, every product template
            some product, every agent template some non-reactant input.
decomp/R    as decomp, with reactant templates restricted to REACTANT-role components.
"""

import json
import sys

import pyarrow.parquet as pq
from rdkit import Chem, RDLogger
from rdkit.Chem import rdChemReactions

from compare import QUERIES, cartridge_match, cartridge_reaction, molecules

RDLogger.DisableLog("rdApp.*")


def sides(smiles):
    """Returns sanitized reactant, agent, and product molecules, cartridge-style."""
    try:
        reactants, agents, products = smiles.split(">")
    except ValueError:
        return None
    parse = lambda part: [m for m in (Chem.MolFromSmiles(s) for s in part.split(".") if s) if m]
    reactants, agents, products = parse(reactants), parse(agents), parse(products)
    mapped = any(a.GetAtomMapNum() for m in reactants + products for a in m.GetAtoms())
    if mapped:
        kept = []
        for m in reactants:
            fraction = sum(1 for a in m.GetAtoms() if a.GetAtomMapNum()) / max(m.GetNumAtoms(), 1)
            (kept if fraction >= 0.2 else agents).append(m)
        reactants = kept
    return reactants, agents, products


def every(templates, mols):
    return all(any(m.HasSubstructMatch(t) for m in mols) for t in templates)


def main():
    rows = pq.read_table(sys.argv[1]).to_pylist()
    queries = {}
    for name, smarts in QUERIES.items():
        q = rdChemReactions.ReactionFromSmarts(smarts)
        q.Initialize()
        queries[name] = q
    reactions = [cartridge_reaction(r["rxn_smiles"]) if r["rxn_smiles"] else None for r in rows]
    split = [sides(r["rxn_smiles"]) if r["rxn_smiles"] else None for r in rows]
    inputs = [molecules(r["inputs"]) for r in rows]
    products = [molecules(r["products"]) for r in rows]
    out = {}
    for name, q in queries.items():
        R, P, A = list(q.GetReactants()), list(q.GetProducts()), list(q.GetAgents())
        sets = {k: set() for k in ("cartridge", "strict", "decomp", "decomp/R")}
        for k, row in enumerate(rows):
            rid = row["reaction_id"]
            if cartridge_match(reactions[k], q):
                sets["cartridge"].add(rid)
            if split[k] is not None:
                re, ag, pr = split[k]
                if every(R, re) and every(P, pr) and every(A, ag):
                    sets["strict"].add(rid)
            ins = [m for m, _ in inputs[k] if m is not None]
            reacts = [m for m, role in inputs[k] if m is not None and role == "REACTANT"]
            non = [m for m, role in inputs[k] if m is not None and role != "REACTANT"]
            prods = [m for m, _ in products[k] if m is not None]
            if every(R, ins) and every(P, prods) and every(A, non):
                sets["decomp"].add(rid)
            if every(R, reacts) and every(P, prods) and every(A, non):
                sets["decomp/R"].add(rid)
        strict = sets["strict"]
        row_out = {k: len(v) for k, v in sets.items()}
        for k in ("cartridge", "decomp", "decomp/R"):
            union = strict | sets[k]
            row_out[f"jaccard strict~{k}"] = round(len(strict & sets[k]) / len(union), 3) if union else 1.0
            row_out[f"strict only vs {k}"] = len(strict - sets[k])
            row_out[f"{k} only"] = len(sets[k] - strict)
        out[name] = row_out
        print(f"{name:28} " + "  ".join(f"{k}={v}" for k, v in row_out.items()), flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)


if __name__ == "__main__":
    main()
