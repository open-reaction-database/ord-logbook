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

"""Compares readings of a reaction SMARTS over the sample, each template on its own molecule.

cartridge     RDKit's hasReactionSubstructMatch, as the cartridge runs it: any one
              template per side, after a template-count check, on the reaction SMILES.
intended      every template matches a different molecule on its side of the reaction
              SMILES, after the cartridge's move of mostly-unmapped reactants to agents.
decomposition every reactant template matches a different REACTANT-role component, every
              product template a different product, every agent template a different
              non-reactant input: what ord_schema.search's reaction_smarts compiles to.
"""

import itertools
import json
import sys

import pyarrow.parquet as pq
from rdkit import RDLogger
from rdkit.Chem import rdChemReactions

from compare import QUERIES, cartridge_match, cartridge_reaction, molecules
from compare2 import sides

RDLogger.DisableLog("rdApp.*")


def distinct(templates, mols):
    """Whether each template matches a different molecule."""
    hits = [[i for i, m in enumerate(mols) if m.HasSubstructMatch(t)] for t in templates]
    return all(hits) and any(
        len(set(choice)) == len(choice) for choice in itertools.product(*hits)
    )


def jaccard(a, b):
    union = a | b
    return round(len(a & b) / len(union), 3) if union else 1.0


def main():
    rows = pq.read_table(sys.argv[1]).to_pylist()
    reactions = [cartridge_reaction(r["rxn_smiles"]) if r["rxn_smiles"] else None for r in rows]
    split = [sides(r["rxn_smiles"]) if r["rxn_smiles"] else None for r in rows]
    inputs = [molecules(r["inputs"]) for r in rows]
    products = [molecules(r["products"]) for r in rows]
    out = {}
    for name, smarts in QUERIES.items():
        q = rdChemReactions.ReactionFromSmarts(smarts)
        q.Initialize()
        R, P, A = list(q.GetReactants()), list(q.GetProducts()), list(q.GetAgents())
        sets = {k: set() for k in ("cartridge", "intended", "decomposition")}
        for k, row in enumerate(rows):
            rid = row["reaction_id"]
            if cartridge_match(reactions[k], q):
                sets["cartridge"].add(rid)
            if split[k] is not None:
                re, ag, pr = split[k]
                if distinct(R, re) and distinct(P, pr) and distinct(A, ag):
                    sets["intended"].add(rid)
            reacts = [m for m, role in inputs[k] if m is not None and role == "REACTANT"]
            non = [m for m, role in inputs[k] if m is not None and role != "REACTANT"]
            prods = [m for m, _ in products[k] if m is not None]
            if distinct(R, reacts) and distinct(P, prods) and distinct(A, non):
                sets["decomposition"].add(rid)
        intended = sets["intended"]
        row_out = {k: len(v) for k, v in sets.items()}
        for k in ("cartridge", "decomposition"):
            row_out[f"jaccard intended~{k}"] = jaccard(intended, sets[k])
            row_out[f"{k} only"] = len(sets[k] - intended)
            row_out[f"intended only vs {k}"] = len(intended - sets[k])
        out[name] = row_out
        print(f"{name:28} " + "  ".join(f"{k}={v}" for k, v in row_out.items()), flush=True)
    json.dump(out, open(sys.argv[2], "w"), indent=1)


if __name__ == "__main__":
    main()
