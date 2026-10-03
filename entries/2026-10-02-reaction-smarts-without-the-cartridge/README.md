# Reaction SMARTS search without the cartridge

- **Date:** 2026-10-02
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** final
- **Tags:** ord-schema, ord-interface, search, rdkit, reaction-smarts
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

ord-interface searches by reaction SMARTS with the RDKit cartridge's
`reaction @> reaction_from_smarts(...)`, and `ord_schema.search` has no reaction-level
predicate. [The search API entry](../2026-10-02-what-the-search-api-still-needs/README.md)
left two designs — a reaction-level match against each reaction's SMILES, or each
template compiled to a per-compound substructure predicate — and one question that
decides between them: what does `@>` actually enforce?

## Summary

**Less than its spelling suggests, and per-compound decomposition matches what a query
means better than `@>` does.**

`@>` checks each side of the reaction separately, and on each side it succeeds if *any
one* query template matches *any one* molecule, after checking that the reaction has at
least as many molecules on that side as the query has templates
(RDKit's `ReactionUtils.cpp`, `hasReactionMoleculeTemplateSubstructMatch`). So
`A.B>>C` means "A or B among at least two reactants, and C in a product", not "A and B".

Over 40,000 reactions, against the reading a chemist intends — every template matches a
molecule on its side:

| query | intended | `@>` | decomposition | `@>` agreement | decomposition agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cB(O)O.c[Br,I]>>cc` (Suzuki) | 946 | 7,667 | 973 | 0.12 | 0.97 |
| `c[Br,Cl,I].N>>cN` (Buchwald) | 7,770 | 15,180 | 7,779 | 0.46 | 0.97 |
| `C(=O)O.N>>C(=O)N` (amide) | 10,712 | 13,508 | 11,278 | 0.66 | 0.95 |
| `C=O.N>>CN` (reductive amination) | 19,664 | 21,764 | 20,260 | 0.72 | 0.97 |

Agreement is the Jaccard index with the intended set; decomposition here restricts
reactant templates to `REACTANT`-role components. On single-template sides `@>` and the
intended reading coincide, and decomposition agrees with both at 0.97 to 1.0.

**Recommendation: a `reaction_smarts` predicate that compiles to per-compound
predicates, and no attempt to reproduce `@>`.** Swapping ord-interface to it narrows the
answer to every multi-template reaction SMARTS, which is a correction to call out when
the swap happens rather than a regression to avoid.

## Method

- **Semantics.** [`semantics.sql`](assets/semantics.sql), literal reactions against
  `@>`, run by [`run_sql.py`](assets/run_sql.py) on a throwaway Postgres with the RDKit
  cartridge 4.8.0 at its default settings; output in
  [`semantics.txt`](assets/semantics.txt). The rule was then read from RDKit's source
  (`Code/GraphMol/ChemReactions/ReactionUtils.cpp`, master). Production's Aurora
  instance was not queried, and its cartridge version was not checked.
- **Emulation.** [`compare.py`](assets/compare.py) reproduces `@>` in Python — build the
  reaction as `reaction_from_smiles` does, move mostly-unmapped reactants to agents,
  call `HasReactionSubstructMatch` — and checks it against the real cartridge on 6,000
  sampled reactions and 11 queries. It agrees exactly on 10; on the one query using
  hydrogen-count primitives the cartridge matches 912 and the emulation 762.
- **Sample.** [`sample.py`](assets/sample.py): 20,000 reactions from the USPTO dataset
  and 20,000 from the other 52 datasets, reservoir samples with seed 7, from the local
  projection tree.
- **Comparison.** [`compare2.py`](assets/compare2.py) computes four readings of each
  query over the sample: `@>`; the intended reading, every template matching a molecule
  on its side of the reaction SMILES after the cartridge's move of unmapped reactants;
  decomposition over all input components; and decomposition with reactant templates
  restricted to `REACTANT`-role components. Results in
  [`compare2.json`](assets/compare2.json), and `@>` against plain decomposition, with
  example reaction IDs, in [`compare.json`](assets/compare.json).

## Findings

### 1. What `@>` checks

| behavior | evidence |
| --- | --- |
| any one template per side matches any one molecule | `B.C(=O)O>>` matches a reaction with no boron (T8); RDKit source |
| the reaction needs at least as many molecules per side as the query has templates | `N.C(=O)O>>` fails on a reaction with one reactant holding both groups (T4) |
| atom maps in the query are ignored | swapping the maps between templates still matches (T1b) |
| in an atom-mapped reaction, a reactant under 20% mapped is an agent | unmapped dichloromethane matches as an agent template, not a reactant one (T3, T3b) |
| chirality is ignored, whatever `rdkit.do_chiral_sss` says | T5, T5b |
| hydrogen-count primitives sometimes fail | `C(=O)[OH]` misses a reaction that `C(=O)O` matches (T2, T2b); the cartridge's 912 against the emulation's 762 says when is not simple |

The first row is what makes `@>` loose. Of the 7,667 sampled reactions it returns for
the Suzuki query, 6,722 — 88% — fail the intended reading; one is an acid chloride
formation with no boron anywhere, matched on its aryl bromide alone.

The second row cuts the other way. 1,102 sampled reactions satisfy the intended amide
reading and `@>` rejects them, as it does 2,371 for reductive amination and 520 for
Buchwald, every one of them because the reaction has fewer reactants than the query has
templates: one molecule carrying both groups, or a partner moved to agents for being
unmapped. So `@>` both adds reactions a query does not describe and drops ones it does.

Agent templates never match in practice: the reaction SMILES the ORM stores carry no
agents, so only reactants moved there by the unmapped rule can match one, and `>[Pd]>`
matched none of the 40,000.

### 2. Decomposition matches the intended reading

Restricting reactant templates to `REACTANT`-role components brings decomposition
within 0.94 to 1.0 of the intended reading on every query but the agent one (finding
3), and what differs is mostly extra rather than missing: on the amide query it adds
570 reactions and misses 4; using every input component gives 0.92 to 1.0, with the losses on USPTO reactions
where a template such as `N` matches a solvent or reagent the reaction SMILES does not
list as a reactant — acetonitrile, in one example. The full table is in [`compare2.json`](assets/compare2.json).

The few percent that remain are reactions where the components and the reaction SMILES
disagree about what was a reactant, which is a property of the record rather than of
either design.

### 3. Where decomposition differs by design

- **Agents.** Decomposition reads catalysts, reagents, and solvents from the components,
  where `@>` cannot: 2,908 sampled reactions have a palladium-containing non-reactant
  input.
- **Chirality.** Decomposition inherits the substructure predicate's default, which
  respects drawn stereocenters
  ([ord-schema#1091](https://github.com/open-reaction-database/ord-schema/pull/1091));
  `@>` ignores them.
- **Hydrogen counts.** Decomposition matches against sanitized molecules, so `[OH]` and
  `[NH2]` behave as they do in any substructure search.
- **Atom maps.** Neither checks them, so neither can say which atoms a reaction
  changed; a template-to-template mapping check would be a different feature.
- **Distinct components.** Neither requires each template to match a different
  molecule.

### 4. Every reaction is reachable

Across the corpus, all 2,427,881 reactions with a reaction SMILES also have input
components and products, so decomposition reaches every reaction `@>` can. The other
410 have no reaction SMILES, so `@>` cannot see them at all and decomposition can.

## Conclusions / next steps

1. **Add `reaction_smarts` to the grammar**, compiled per template: each reactant
   template to an `exists` over input components with that substructure and role
   `REACTANT`, each product template to an `exists` over products, each agent template
   to an `exists` over input components whose role is not `REACTANT`. It reuses the
   substructure library and the occurrence index, so it needs no new artifact.
2. **Call out the narrower answers at the ord-interface swap.** A multi-template query
   returns what it says, which on the Suzuki query is one reaction in eight of what
   `@>` returns today.
3. **Leave a reaction-level match aside** unless atom-map-aware transformation search
   becomes a requirement; that, not parity, is the only thing it would add.

## References

- [`assets/`](assets/): `semantics.sql` and `semantics.txt`, `run_sql.py`, `sample.py`,
  `compare.py` and `compare.json`, `compare2.py` and `compare2.json`.
- RDKit
  [`ReactionUtils.cpp`](https://github.com/rdkit/rdkit/blob/master/Code/GraphMol/ChemReactions/ReactionUtils.cpp)
  — `hasReactionSubstructMatch` and the template matcher it calls.
- [What the search API still needs before ord-interface can use it](../2026-10-02-what-the-search-api-still-needs/README.md)
  — finding 1, the question this answers.
- ord-interface `ReactionSmartsQuery` in `ord_interface/api/queries.py` — the `@>` query
  this would replace.
