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

"""Hand-curated name -> SMILES for the frequent name-only solvents/reagents.

Only single, well-defined compounds are included. Deliberately excluded: generic classes
(amine, ester), undefined mixtures (petroleum ether, xylenes), supported/heterogeneous catalysts
(Pd/C), organometallic complexes (Pd(PPh3)4), and polymers/materials (Teflon, nylon). Every SMILES
is canonicalized through RDKit; anything that fails to parse is reported and dropped.
"""

import csv
import sys

from rdkit import Chem
from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")

# name (as it appears in the data) -> a SMILES for the intended compound.
# "typo:" notes flag names that are near-certain misspellings resolved to the intended reagent.
CURATED: dict[str, str] = {
    # --- solvents (single, well-defined) ---
    "hexanes": "CCCCCC", "Hexanes": "CCCCCC",
    "heptanes": "CCCCCCC",
    # --- amine bases ---
    "TEA": "CCN(CC)CC",
    "N,N-dimethylaminopyridine": "CN(C)c1ccncc1",
    "4-N,N-dimethylaminopyridine": "CN(C)c1ccncc1",
    # --- coupling / activating reagents ---
    "N,N′-Carbonyldiimidazole": "O=C(n1ccnc1)n1ccnc1",
    "N,N′-carbonyldiimidazole": "O=C(n1ccnc1)n1ccnc1",
    "N,N'-carbonyldiimidazole": "O=C(n1ccnc1)n1ccnc1",
    # --- copper salts ---
    "cuprous iodide": "[Cu]I",
    "cuprous chloride": "[Cu]Cl",
    "cuprous cyanide": "[Cu]C#N",
    "CuBr": "[Cu]Br",
    # --- tin / iron / mercury halides ---
    "stannous chloride": "Cl[Sn]Cl",
    "stannous chloride dihydrate": "Cl[Sn]Cl.O.O",
    "stannic chloride": "Cl[Sn](Cl)(Cl)Cl",
    "ferric chloride": "Cl[Fe](Cl)Cl",
    "mercuric chloride": "Cl[Hg]Cl",
    # --- oxidants / metals ---
    "NaIO4": "O=I(=O)(=O)[O-].[Na+]",
    "PtO2": "O=[Pt]=O",
    "Mg": "[Mg]",
    "Na": "[Na]",
    "reduced iron": "[Fe]",
    "Si": "[Si]",
    # --- inorganic salts (incl. clear typos) ---
    "NH4OAc": "CC(=O)[O-].[NH4+]",
    "NH4HCO3": "OC(=O)[O-].[NH4+]",
    "KHCO3": "OC(=O)[O-].[K+]",
    "NaH2PO4": "OP(=O)(O)[O-].[Na+]",
    "Na2S2O5": "O=S([O-])S(=O)(=O)[O-].[Na+].[Na+]",
    "NaSO4": "[O-]S(=O)(=O)[O-].[Na+].[Na+]",  # typo: Na2SO4
    "Mg2SO4": "[O-]S(=O)(=O)[O-].[Mg+2]",  # typo: MgSO4
    "sodium sulfate anhydride": "[O-]S(=O)(=O)[O-].[Na+].[Na+]",
    # --- phosphine ligand ---
    "PCy3": "C1CCC(CC1)P(C1CCCCC1)C1CCCCC1",
    # --- silica (support/desiccant, but a defined oxide) ---
    "SiO2": "O=[Si]=O",
    # --- denatured ethanol ---
    "IMS": "CCO",
    "industrial methylated spirit": "CCO",
}


def main() -> None:
    out = csv.writer(sys.stdout, delimiter="\t")
    out.writerow(["name", "smiles"])
    bad = []
    for name, smiles in CURATED.items():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            bad.append((name, smiles))
            continue
        out.writerow([name, Chem.MolToSmiles(mol)])
    if bad:
        for name, smiles in bad:
            print(f"INVALID {name!r}: {smiles!r}", file=sys.stderr)
    print(f"curated={len(CURATED)} valid={len(CURATED) - len(bad)} invalid={len(bad)}", file=sys.stderr)


if __name__ == "__main__":
    main()
