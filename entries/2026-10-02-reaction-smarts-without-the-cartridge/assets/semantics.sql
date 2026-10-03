-- Copyright 2026 Open Reaction Database Project Authors
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Literal reactions against the cartridge's `@>`; run with run_sql.py.
SELECT 'T1 query maps, consistent', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('[C:1](=O)[OH].[N:2]>>[C:1](=O)[N:2]'::cstring);
SELECT 'T1b query maps, swapped', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('[C:1](=O)[OH].[N:2]>>[C:2](=O)[N:1]'::cstring);
SELECT 'T2 unmapped rxn, acid template written with [OH]', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('C(=O)[OH]>>'::cstring);
SELECT 'T2b unmapped rxn, acid template written with O', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('C(=O)O>>'::cstring);
SELECT 'T3 mapped rxn, unmapped DCM as reactant template', reaction_from_smiles('[CH3:1][C:2](=[O:3])O.[NH2:4][CH3:5].ClCCl>>[CH3:1][C:2](=[O:3])[NH:4][CH3:5]'::cstring) @> reaction_from_smarts('ClCCl>>'::cstring);
SELECT 'T3b mapped rxn, DCM as agent template', reaction_from_smiles('[CH3:1][C:2](=[O:3])O.[NH2:4][CH3:5].ClCCl>>[CH3:1][C:2](=[O:3])[NH:4][CH3:5]'::cstring) @> reaction_from_smarts('>ClCCl>'::cstring);
SELECT 'T3c mapped rxn, mapped acid as reactant template', reaction_from_smiles('[CH3:1][C:2](=[O:3])O.[NH2:4][CH3:5].ClCCl>>[CH3:1][C:2](=[O:3])[NH:4][CH3:5]'::cstring) @> reaction_from_smarts('C(=O)O>>'::cstring);
SELECT 'T3d mapped rxn without DCM, acid template', reaction_from_smiles('[CH3:1][C:2](=[O:3])O.[NH2:4][CH3:5]>>[CH3:1][C:2](=[O:3])[NH:4][CH3:5]'::cstring) @> reaction_from_smarts('C(=O)O>>'::cstring);
SELECT 'T3e mapped rxn, acid template with amide product', reaction_from_smiles('[CH3:1][C:2](=[O:3])O.[NH2:4][CH3:5].ClCCl>>[CH3:1][C:2](=[O:3])[NH:4][CH3:5]'::cstring) @> reaction_from_smarts('C(=O)O>>C(=O)N'::cstring);
SELECT 'T4 two templates, one reactant (fails the count check)', reaction_from_smiles('NCCC(=O)O>>O=C1CCN1'::cstring) @> reaction_from_smarts('N.C(=O)O>>'::cstring);
SELECT 'T4b two templates, two reactants', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('N.C(=O)O>>'::cstring);
SELECT 'T5 chirality, default off', reaction_from_smiles('C[C@H](N)C(=O)O>>C[C@H](N)C(=O)OC'::cstring) @> reaction_from_smarts('C[C@@H](N)C(=O)O>>'::cstring);
SET rdkit.do_chiral_sss = on;
SELECT 'T5b chirality on', reaction_from_smiles('C[C@H](N)C(=O)O>>C[C@H](N)C(=O)OC'::cstring) @> reaction_from_smarts('C[C@@H](N)C(=O)O>>'::cstring);
SET rdkit.do_chiral_sss = off;
SELECT 'T6 product-only template', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('>>C(=O)N'::cstring);
SELECT 'T7 product pattern on reactant side', reaction_from_smiles('CC(=O)O.NC>>CC(=O)NC'::cstring) @> reaction_from_smarts('C(=O)N>>'::cstring)
;
SELECT 'T8 one of two templates absent', reaction_from_smiles('CC(=O)O.NC.ClCCl>>CC(=O)NC'::cstring) @> reaction_from_smarts('B.C(=O)O>>'::cstring);
SELECT 'T9 both templates absent', reaction_from_smiles('CC(=O)O.NC.ClCCl>>CC(=O)NC'::cstring) @> reaction_from_smarts('B.[Xe]>>'::cstring);
