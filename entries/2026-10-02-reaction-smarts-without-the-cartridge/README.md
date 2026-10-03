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
different molecule on its side:

| query | intended | `@>` | decomposition | `@>` agreement | decomposition agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cB(O)O.c[Br,I]>>cc` (Suzuki) | 943 | 7,667 | 971 | 0.12 | 0.97 |
| `c[Br,Cl,I].N>>cN` (Buchwald) | 5,715 | 15,180 | 6,052 | 0.38 | 0.90 |
| `C(=O)O.N>>C(=O)N` (amide) | 7,965 | 13,508 | 9,328 | 0.59 | 0.85 |
| `C=O.N>>CN` (reductive amination) | 13,812 | 21,764 | 16,066 | 0.63 | 0.85 |

Agreement is the Jaccard index with the intended set. Decomposition is what
`reaction_smarts` compiles to: each reactant template on a different `REACTANT`-role
component, each product template on a different product. On single-template sides `@>`
and the intended reading coincide, and decomposition agrees with both at 0.98 to 1.0.

**Correction, same day.** The first version of this entry let one molecule satisfy two
templates, in the intended reading and in decomposition alike. That reading accepts a Boc
deprotection as an amide coupling, because the carbamate holds both `C(=O)O` and `N`,
and it added 1,950 amide reactions to decomposition. The tables now hold each template
to a different molecule, and so does
[ord-schema#1093](https://github.com/open-reaction-database/ord-schema/pull/1093).

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
- **Comparison.** [`compare3.py`](assets/compare3.py) computes three readings of each
  query over the sample: `@>`; the intended reading, every template matching a different
  molecule on its side of the reaction SMILES after the cartridge's move of unmapped
  reactants; and decomposition, every template matching a different component in its
  role. Results in [`compare3.json`](assets/compare3.json).
  [`extras.py`](assets/extras.py) classifies the reactions decomposition adds
  ([`extras.txt`](assets/extras.txt)).
- **Earlier comparison.** [`compare2.py`](assets/compare2.py) and
  [`compare2.json`](assets/compare2.json) are the same readings with one molecule
  allowed to satisfy several templates, plus decomposition over all input components;
  [`compare.json`](assets/compare.json) is `@>` against that decomposition, with example
  reaction IDs.

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
the Suzuki query, 6,724 — 88% — fail the intended reading; one is an acid chloride
formation with no boron anywhere, matched on its aryl bromide alone.

The second row only narrows. Templates on different molecules need at least that many
molecules, so every reaction satisfying the intended reading passes the count, and on
every query without hydrogen-count primitives `@>` returns a superset of the intended
reading. Its error is all in what it adds.

Agent templates never match in practice: the reaction SMILES the ORM stores carry no
agents, so only reactants moved there by the unmapped rule can match one, and `>[Pd]>`
matched none of the 40,000.

### 2. Decomposition matches the intended reading

Decomposition agrees with the intended reading at 0.85 to 0.97 on the two-template
queries and 0.98 to 1.0 on the single-template ones, leaving out the agent query
(finding 3). Nearly all of the difference is reactions decomposition adds rather than
misses: on the amide query it adds 1,383 and misses 20. The full table is in
[`compare3.json`](assets/compare3.json).

The added reactions are mostly an artifact of the intended reading's own rule. In 1,357
of the 1,383 amide additions, the reaction SMILES lists the amine as a reactant, but the
cartridge's rule moves it to agents for having under 20% of its atoms mapped. The record's
components call it a `REACTANT`, and decomposition believes them. The same rule
accounts for 394 of Buchwald's 477 additions and 2,191 of reductive amination's 2,296
([`extras.txt`](assets/extras.txt)). The few that remain are reactions where the
components and the reaction SMILES disagree about what was a reactant, which is a
property of the record rather than of either design. Reading reactant templates from
every input component, rather than from `REACTANT` components only, adds reactions where
a template such as `N` matches a solvent or reagent, such as acetonitrile.

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
- **Distinct molecules.** Decomposition requires the templates on a side to match
  different components, checked as a count per subset of two or more templates; `@>`
  checks only that the side holds enough molecules. A grouped template, `(A.B)`, asks for
  both pieces in one molecule.

### 4. Every reaction is reachable

Across the corpus, all 2,427,881 reactions with a reaction SMILES also have input
components and products, so decomposition reaches every reaction `@>` can. The other
410 have no reaction SMILES, so `@>` cannot see them at all and decomposition can.

## Conclusions / next steps

1. **Add `reaction_smarts` to the grammar**, compiled per template: each reactant
   template to an `exists` over input components with that substructure and role
   `REACTANT`, each product template to an `exists` over products, each agent template
   to an `exists` over input components whose role is not `REACTANT`, plus a count per
   subset of two or more templates on a side holding them to different molecules. It
   reuses the substructure library, the occurrence index, and the pivots, so it needs no
   new artifact.
2. **Call out the narrower answers at the ord-interface swap.** A multi-template query
   returns what it says, which on the Suzuki query is one reaction in eight of what
   `@>` returns today.
3. **Leave a reaction-level match aside** unless atom-map-aware transformation search
   becomes a requirement; that, not parity, is the only thing it would add.

## References

- [`assets/`](assets/): `semantics.sql` and `semantics.txt`, `run_sql.py`, `sample.py`,
  `compare.py` and `compare.json`, `compare2.py` and `compare2.json`, `compare3.py` and
  `compare3.json`, `extras.py` and `extras.txt`.
- RDKit
  [`ReactionUtils.cpp`](https://github.com/rdkit/rdkit/blob/master/Code/GraphMol/ChemReactions/ReactionUtils.cpp)
  — `hasReactionSubstructMatch` and the template matcher it calls.
- [What the search API still needs before ord-interface can use it](../2026-10-02-what-the-search-api-still-needs/README.md)
  — finding 1, the question this answers.
- ord-interface `ReactionSmartsQuery` in `ord_interface/api/queries.py` — the `@>` query
  this would replace.
