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

"""Says why decomposition accepts reactions the intended reading rejects."""

import collections
import sys

import pyarrow.parquet as pq
from rdkit import Chem, RDLogger
from rdkit.Chem import rdChemReactions

from compare import QUERIES, molecules
from compare2 import sides
from compare3 import distinct

RDLogger.DisableLog("rdApp.*")


def raw_sides(smiles):
    reactants, agents, products = smiles.split(">")
    parse = lambda part: [m for m in (Chem.MolFromSmiles(s) for s in part.split(".") if s) if m]
    return parse(reactants), parse(agents), parse(products)


rows = pq.read_table(sys.argv[1]).to_pylist()
for name in ("amide", "buchwald", "reductive amination", "suzuki"):
    q = rdChemReactions.ReactionFromSmarts(QUERIES[name])
    q.Initialize()
    R, P = list(q.GetReactants()), list(q.GetProducts())
    why = collections.Counter()
    for row in rows:
        ins = molecules(row["inputs"])
        reacts = [m for m, role in ins if m is not None and role == "REACTANT"]
        prods = [m for m, _ in molecules(row["products"]) if m is not None]
        if not (distinct(R, reacts) and distinct(P, prods)):
            continue
        if not row["rxn_smiles"]:
            why["no reaction SMILES"] += 1
            continue
        split = sides(row["rxn_smiles"])
        if split is None:
            why["unparseable reaction SMILES"] += 1
            continue
        re, ag, pr = split
        if distinct(R, re) and distinct(P, pr):
            continue
        raw = raw_sides(row["rxn_smiles"])
        if distinct(R, raw[0]) and distinct(P, raw[2]):
            why["a reactant moved to agents as mostly unmapped"] += 1
        elif not distinct(P, pr):
            why["product side differs"] += 1
        elif len(re) < len(R):
            why["fewer reactants in the reaction SMILES than templates"] += 1
        else:
            why["reactant side differs otherwise"] += 1
    print(name, dict(why.most_common()), flush=True)
