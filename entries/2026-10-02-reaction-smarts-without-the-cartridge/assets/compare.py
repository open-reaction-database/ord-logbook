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

"""Compares the RDKit cartridge's reaction match with a per-compound decomposition.

1. Emulates the cartridge's `reaction @> reaction_from_smarts(...)` in Python and checks
   the emulation against a real cartridge on the first VALIDATE reactions.
2. Over the whole sample, compares the cartridge's answer with decomposition: every
   reactant template matches some input component, every product template some product,
   every agent template some non-reactant input, each independently.
"""

import collections
import json
import sys
import time

import psycopg
import pyarrow.parquet as pq
import testing.postgresql
from rdkit import Chem, RDLogger
from rdkit.Chem import rdChemReactions

RDLogger.DisableLog("rdApp.*")

QUERIES = {
    "amide": "C(=O)O.N>>C(=O)N",
    "amide, H counts": "[CX3](=O)[OX2H1].[NX3;H2]>>C(=O)N",
    "amide, atom maps": "[C:1](=O)O.[N:2]>>[C:1](=O)[N:2]",
    "suzuki": "cB(O)O.c[Br,I]>>cc",
    "boc removal": "CC(C)(C)OC(=O)N>>N",
    "ester hydrolysis": "C(=O)OC>>C(=O)O",
    "buchwald": "c[Br,Cl,I].N>>cN",
    "reductive amination": "C=O.N>>CN",
    "pyridine product": ">>c1ccncc1",
    "aryl boronic acid reactant": "cB(O)O>>",
    "palladium agent": ">[Pd]>",
}
VALIDATE = 3000


def cartridge_reaction(smiles):
    """Builds a reaction the way the cartridge's reaction_from_smiles does."""
    try:
        rxn = rdChemReactions.ReactionFromSmarts(smiles, useSmiles=True)
    except ValueError:
        return None
    if rxn is None:
        return None
    rxn.Initialize()
    if rdChemReactions.HasReactionAtomMapping(rxn):
        rxn.RemoveUnmappedReactantTemplates(thresholdUnmappedAtoms=0.2)
    return rxn


def cartridge_match(rxn, query):
    """Returns whether rxn @> query, treating RDKit's precondition errors as no match."""
    if rxn is None:
        return False
    try:
        return rdChemReactions.HasReactionSubstructMatch(rxn, query, includeAgents=True)
    except RuntimeError:
        return False


def molecules(entries):
    out = []
    for entry in entries or []:
        mol = Chem.MolFromSmiles(entry["smiles"]) if entry["smiles"] else None
        out.append((mol, entry["role"]))
    return out


def decomposition(query, inputs, products):
    for template in query.GetReactants():
        if not any(m is not None and m.HasSubstructMatch(template) for m, _ in inputs):
            return False
    for template in query.GetProducts():
        if not any(m is not None and m.HasSubstructMatch(template) for m, _ in products):
            return False
    for template in query.GetAgents():
        if not any(
            m is not None and role != "REACTANT" and m.HasSubstructMatch(template)
            for m, role in inputs
        ):
            return False
    return True


def main():
    sample, out_path = sys.argv[1], sys.argv[2]
    rows = pq.read_table(sample).to_pylist()
    queries = {name: rdChemReactions.ReactionFromSmarts(s) for name, s in QUERIES.items()}
    for q in queries.values():
        q.Initialize()
    start = time.perf_counter()
    reactions = [cartridge_reaction(r["rxn_smiles"]) if r["rxn_smiles"] else None for r in rows]
    inputs = [molecules(r["inputs"]) for r in rows]
    products = [molecules(r["products"]) for r in rows]
    print(f"parsed {len(rows)} reactions in {time.perf_counter() - start:.1f}s", flush=True)

    # 1. Emulation against the real cartridge.
    disagreements = {}
    with testing.postgresql.Postgresql() as pg, psycopg.connect(pg.url(), autocommit=True) as conn:
        conn.execute("CREATE EXTENSION rdkit")
        conn.execute("CREATE TABLE r (i int, smi text)")
        with conn.cursor().copy("COPY r (i, smi) FROM STDIN") as copy:
            for i, row in enumerate(rows[:VALIDATE] + rows[len(rows) // 2 : len(rows) // 2 + VALIDATE]):
                if row["rxn_smiles"]:
                    copy.write_row((i, row["rxn_smiles"]))
        conn.execute("ALTER TABLE r ADD COLUMN rxn reaction")
        conn.execute("UPDATE r SET rxn = reaction_from_smiles(smi::cstring)")
        index = list(range(VALIDATE)) + list(range(len(rows) // 2, len(rows) // 2 + VALIDATE))
        for name, smarts in QUERIES.items():
            real = {index[i] for (i,) in conn.execute(
                "SELECT i FROM r WHERE rxn @> reaction_from_smarts(%s::cstring)", (smarts,)
            ).fetchall()}
            emulated = {k for k in index if cartridge_match(reactions[k], queries[name])}
            disagreements[name] = (len(real), len(emulated), len(real ^ emulated))
    print("emulation vs cartridge on", 2 * VALIDATE, "reactions (real, emulated, differ):", flush=True)
    for name, counts in disagreements.items():
        print(f"  {name:28} {counts}", flush=True)

    # 2. Cartridge against decomposition over the whole sample.
    results = {}
    for name, query in queries.items():
        tally = collections.Counter()
        examples = collections.defaultdict(list)
        for k, row in enumerate(rows):
            c = cartridge_match(reactions[k], query)
            d = decomposition(query, inputs[k], products[k])
            key = (row["source"], "both" if c and d else "cartridge only" if c else "decomposition only" if d else None)
            if key[1]:
                tally[key] += 1
                if key[1] != "both" and len(examples[key]) < 3:
                    examples[key].append(row["reaction_id"])
        results[name] = {f"{s}/{k}": v for (s, k), v in sorted(tally.items())}
        results[name]["examples"] = {f"{s}/{k}": v for (s, k), v in examples.items()}
        print(f"{name:28} " + ", ".join(f"{s}/{k}={v}" for (s, k), v in sorted(tally.items())), flush=True)
    with open(out_path, "w") as handle:
        json.dump({"validation": disagreements, "comparison": results}, handle, indent=1)


if __name__ == "__main__":
    main()
