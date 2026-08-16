# Reaction classification for the ORD: RXNO is a vocabulary, not a classifier — four classifiers benchmarked, plus a draft RXNO crosswalk

- **Date:** 2026-07-02
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** classification, rxno, namerxn, rxn-insight, rxnfp, syncat, reactionclassifier, atom-mapping, ontology, benchmark

## Question

The ORD pipeline uses [Rxn-INSIGHT](https://github.com/mrodobbe/Rxn-INSIGHT) for reaction classification and naming. I'd prefer output that maps onto the **RXNO** (Name Reaction Ontology) — or NameRxn, but that's proprietary. What would it take to build a classification system that emits RXNO categories?

Two follow-ups widened the scope and reshaped the answer:

1. Is `RXNMapper_v2` a genuine improvement over the original atom mapper?
2. Is it acceptable to target **NameRxn** classes instead of RXNO, if a good open model already exists or enough public labels exist to train one?

A third pass (2026-07-03) asked whether RXNO IDs can be bolted onto the strongest open classifier's output.

## Summary

- **RXNO is a controlled vocabulary, not a classifier.** RSC-maintained, CC-BY, 653 native reaction terms, named-reaction-dominated; it ships no model. **NameRxn** (NextMove, proprietary) is the classifier that emits RXNO IDs in practice — it is the crosswalk the ontology relies on.
- **Verified: the public Schneider-50k dataset is labeled with *real* NameRxn `N.N.N` codes**, not anonymized integers. I fetched `schneider50k.tsv` and read values like `6.1.5`, `7.1.1`, `1.8.5`, `1.7.9`. Those codes map straight into RXNO, so an open classifier gives real NameRxn/RXNO-mappable labels **today** — with a hard **50-leaf-class ceiling**. The full ~967-leaf space has no open dataset.
- **Benchmarked four classifiers on the same 1,572 ORD reactions.** Throughput: rxnfp 186.1, ReactionClassifier 169.8, SynCat 112.1, **Rxn-INSIGHT 8.6 rxn/s**. Rxn-INSIGHT is ~20x slower for one reason — it runs an ALBERT atom-mapping transformer per reaction. Every alternative is atom-mapping-free, and **none needs a GPU**.
- **The Schwaller ReactionClassifier runs fully offline** — `rdkit`/`torch`/`numpy` only, no LLM at inference, no atom mapping. It resolves to 6,962 operational classes, abstains when no shipped template reproduces the product, and beats Rxn-INSIGHT on specific-label coverage (58.7% vs 51.4%). Its codes are its **own** taxonomy, not RXNO/NameRxn IDs.
- **Drafted a ReactionClassifier → RXNO crosswalk over all 6,926 classes.** An LLM pass maps **38% of ORD-weighted reactions to a *specific* RXNO named reaction** (vs 7% for naive string matching), but **~48% of ORD chemistry has no RXNO term at all**. That is RXNO's named-reaction-only design ceiling, not a matcher limit. The draft map is **unaudited**.
- **The open decision is granularity** (owner: Steven): 10 superclasses → 50 NameRxn leaves → 6,962 ReactionClassifier codes → full ~967 NameRxn. That choice selects the path; only the last requires a paid license.

**Structural point that makes all of this cheap:** the ORD proto has no RXNO/NameRxn field. Classification is purely derived data, so adding RXNO is a derived-table change, not a schema change.

## Method

### How classification runs in ORD today

Rxn-INSIGHT is live in `ord-schema` (not `ord-interface`):

- `ord-schema/ord_schema/orm/reaction_class.py` calls `Reaction(smiles, rxn_mapper=RXNMapper()).get_reaction_info()` and returns a `(reaction_class, reaction_name)` tuple, e.g. `("C-C Coupling", "Suzuki coupling with boronic acids")`.
- Results land in a dedicated `derived.reaction_classes` table (PK `reaction_id`; two indexed `Text` columns, `reaction_class` / `reaction_name`), populated during the derived post-pass via the optional `--classify_reactions` flag. Rxn-INSIGHT's `"OtherReaction"` sentinel is normalized to NULL.
- We already depend on **rxnmapper** transitively, via a `skearnes/Rxn-INSIGHT` fork (pinned at `eb71946`) for modern NumPy/SciPy, with `transformers>=4.53,<5` and `setuptools<81` pins to keep it importable.
- `ord-interface` and `ord-app` depend on `ord-schema[orm]` but **not** `[reaction-class]`, so there is no downstream coupling. Classification is capped at 4 worker shards because each worker loads a transformer model.

To run it: `pip install ord-schema[reaction-class]`, then `python -m ord_schema.orm.scripts.add_datasets --classify_reactions ...`. Entry points are `classify_reaction_smiles` and `update_reaction_classes`. A local/test Postgres is built via `setup_test_postgres` (`ord-interface/ord_interface/client/build_database.py`). All repos are siblings under `~/github/ord/`; Python runs in the **`ord` conda env** (`~/mambaforge/envs/ord`), whose `bin/initdb` and Postgres binaries drive the local DB, *not* the system PATH.

### Landscape review

Desk research over RXNO, NameRxn, rxnfp, DRFP, SynCat, the Schwaller ReactionClassifier, and both packages calling themselves "the new rxnmapper". The one claim worth verifying by hand — that Schneider-50k carries real NameRxn codes rather than anonymized class integers — was checked by fetching `schneider50k.tsv` and reading the `rxn_class` column directly.

### Hands-on benchmark

Four classifiers timed on the **same 1,572 real ORD reactions**, sampled from `ord-data` with atom maps stripped to unmapped canonical SMILES. Single CPU process, isolated venv, dev Mac, 2026-07-02.

- For the two 50-class models, human-readable names come from NameRxn's `rxnclass2name.json`.
- The **rxnfp** head was trained on the bundled Schneider-50k fingerprints (**0.994** test accuracy).
- **SynCat** runs its shipped `model_schneider.pt`; its output-index → NameRxn-code map was calibrated on the Schneider test split (**0.976** recovered; the paper reports 0.988).

Scripts and a reproduction guide: [`bench/`](bench/).

### ReactionClassifier → RXNO crosswalk

Two passes over all 6,926 ReactionClassifier (RXC) classes, targeting RXNO's 653 native terms — a many-to-one map bounded by RXNO, not by RXC's count.

1. **String/synonym baseline** — match RXC class descriptions against RXNO and MOP names and synonyms.
2. **LLM pass** — 47 parallel agents, one judgment per distinct reaction description, the full RXNO vocabulary in context, `sonnet`. Agents were instructed to prefer the most specific term, to never invent an ID, and to return **null** when no RXNO term genuinely matches.

Scripts and the draft map: [`bench/crosswalk/`](bench/crosswalk/).

## Findings

### What Rxn-INSIGHT actually is

Correcting a common misattribution: it is **Dobbelaere, Lengyel, Stevens & Van Geem (Ghent University), *J. Cheminformatics* 16:37 (2024), MIT-licensed** — not a Schwaller/EPFL project. Its only tie to Schwaller is that it *depends on* rxnmapper. It is **rule-based, not ML**:

- **Class**: 10 superclasses + "Miscellaneous", assigned by bond-electron-matrix (BE) predicates evaluated in a fixed dispatch order (first match wins). The 10 come from **Carey et al. 2006** — the same source as NameRxn's level-1 superclasses.
- **Name**: deterministic matching against **528 curated SMIRKS** templates; the first template whose predicted product matches the actual product wins, else `"OtherReaction"`. No confidence score.
- **Output**: `get_reaction_info()` returns an 18-key dict (`CLASS`, `NAME`, `MAPPED_REACTION`, functional groups, rings, scaffold, tag, etc.).
- **Coverage ceiling (on USPTO)**: ~90% get a superclass, only **~51% get a specific name**, ~10% fall into Miscellaneous. Entirely dependent on atom-mapping quality — the authors flag that BE-matrix classification "becomes inaccurate when the atom mapping fails."

The key implication: Rxn-INSIGHT already emits **named reactions** whose vocabulary overlaps heavily with RXNO's ~500 named reactions, and a superclass scheme sharing RXNO/NameRxn's lineage. That is what makes a crosswalk viable at all.

### The RXNO / NameRxn / IBM RXN landscape

- **RXNO (Name Reaction Ontology)** — RSC-maintained (Colin Batchelor), an OBO Foundry ontology, **CC-BY 4.0**, distributed as OWL + OBO. IDs like `RXNO:0000006` (Diels-Alder). ~653 native reaction terms (OLS reports ~1,019 including imports from BFO/CHEBI/MOP). It is **named-reaction-dominated**; generic mechanistic transformations are delegated to a companion ontology (MOP). **Ships no classifier.** The currently loaded release is a somewhat stale 2021-12-16.
- **NameRxn (NextMove Software)** — proprietary rule-based expert system. Given a reaction it emits a three-level `superclass.category.name` code **and the matching RXNO ID directly** (documented example: `3.1.1 Bromo Suzuki coupling → RXNO:0000140`). ~1,000+ leaf classes; ships in the HazELNut suite.
- **Schneider / USPTO-50k** — the widely used reaction-class benchmarks originate from Schneider, Lowe, Sayle & Landrum (*JCIM* 2015) and are **labeled by NameRxn**. Schneider-50k carries 50 real NameRxn leaf codes; the retrosynthesis USPTO-50k keeps only the 10 superclasses.
- **IBM RXN's open model is `rxnfp`** (Schwaller et al., *Nat. Mach. Intell.* 3, 2021, MIT) — a BERT reaction-fingerprint classifier, ~98% class accuracy, but trained on **NameRxn-labeled** Pistachio, so it is an ML surrogate for a proprietary scheme. Its one fully open label set, USPTO 1k TPL, uses **template-hash** labels, not RXNO. [DRFP](https://github.com/reymond-group/drfp) reaches ~99% of rxnfp's performance without atom mapping.

The 10 top-level classes (USPTO-50k counts):

| # | Superclass | Count |
| --- | --- | --- |
| 1 | Heteroatom alkylation and arylation | 15,204 |
| 2 | Acylation and related processes | 11,972 |
| 3 | C–C bond formation | 5,667 |
| 4 | Heterocycle formation | 909 |
| 5 | Protections | 672 |
| 6 | Deprotections | 8,405 |
| 7 | Reductions | 4,642 |
| 8 | Oxidations | 822 |
| 9 | Functional group interconversion (FGI) | 1,858 |
| 10 | Functional group addition (FGA) | 231 |

**Bottom line for RXNO:** there is no open `(SMILES → RXNO ID)` dataset. Only the proprietary NameRxn produces RXNO IDs; open models predict into NameRxn-derived or template-hash label spaces, neither of which is RXNO.

### Open NameRxn labels: what is public, and at what granularity

- **Schneider-50k** (`schneider50k.tsv`, in the rxnfp + DRFP repos, MIT) — **50 real NameRxn `N.N.N` leaf codes**, 1,000 reactions each (50k total, verified from the file), spanning 9 of the 10 superclasses and 28 categories. Human-readable names come from the sibling `rxnclass2name.json` (e.g. `3.1.1` = "Bromo Suzuki coupling", `10.1.5` = "Wohl-Ziegler bromination"); `rxnclass2id.json` maps the 50 codes to 0–49 for ML. So you get **code + name + RXNO-mappable label**, openly.
- **USPTO-50k** (retrosynthesis; retrosim/GLN, MIT) — only the **10 superclass integers**. Correcting a common claim: Schneider-50k and this USPTO-50k are **not the same reactions relabeled** — they are ~7%-overlapping samples from the same USPTO/Lowe corpus under the same NameRxn taxonomy. Use Schneider-50k when you want leaf codes.
- **USPTO-1k-TPL** — 1,000 classes, but **reaction-template hashes, not NameRxn**. Easy to mistake for "1000 NameRxn classes"; it isn't.
- **Pistachio / NameRxn** — the full **~967 NameRxn leaf classes** live only here, proprietary. No open slice at that granularity.
- **ORD itself** carries no structured NameRxn field (only a free-text `REACTION_TYPE` identifier), so there is nothing in our own data to bootstrap-train from.

Open models that emit these labels:

| Model | Emits | Classes | License | Notes |
| --- | --- | --- | --- | --- |
| **rxnfp** (Schneider classifier) | real NameRxn `N.N.N` | 50 | MIT | fingerprints ship; head must be trained |
| **rxnfp** (1k TPL) | template hashes | 1000 | MIT | not NameRxn |
| **DRFP** + your MLP | whatever you train on | 50 (Schneider) | MIT | fingerprint only, 0.956 on Schneider |
| **SynCat** (2026) | NameRxn (Schneider) | 50 | MIT code + weights (paper CC-BY-NC) | GINE GNN, ~0.988 SOTA, atom-mapping-free |
| `pingzhili` ChemBERTa (HF) | 10 superclasses | 10 | MIT | 87%, reactant/product input |

**SynCat** ([phuocchung123/SynCat](https://github.com/phuocchung123/SynCat)) is **atom-mapping-free** (no rxnmapper dependency), and its edge over rxnfp *grows with granularity* — on 680-class reaction-center clusters it hits 0.982 vs rxnfp's 0.802. It also ships finer-grained label schemes beyond the 50 NameRxn codes — SynTemp reaction-center clusters (143 / 356 / 680 classes) and a 63-class mechanistic set — though those are cluster/mechanism IDs, not NameRxn/RXNO codes.

**The near-NameRxn open outlier — Schwaller ReactionClassifier (2026).** arXiv 2607.01061, MIT, `schwallergroup/ReactionClassifier`; authors include **Maarten Dobbelaere** (the Rxn-INSIGHT author). An agentic-LLM (Gemini 3) pipeline that writes *verifiable* generalized SMIRKS rules and self-expands a 68-class seed into **14,073 classes over 7 levels** (19 superclasses, 106 subclasses, ~1,546 L3 types). Deterministic verification: a rule's template must reproduce the recorded product before a label is emitted. Reported ~97.7% on unseen reactions — matching NameRxn — and expert chemists preferred its labels over NameRxn (82.6% vs 61.8%). Ships a ~666k-reaction labeled USPTO DB (NameRxn columns excluded as proprietary). Caveats: its codes are its **own** taxonomy (not NameRxn/RXNO IDs), OOD coverage on 2025 academic reactions trails NameRxn (~68% vs 89%), and it is a days-old, non-peer-reviewed preprint.

**So, does rxnfp "spit out NameRxn classes"?** Its *Schneider* classifier does — real `N.N.N` codes at 50-leaf granularity. Its 1k-TPL classifier does not. And there are *enough public labels to train* an open NameRxn classifier only up to ~50 leaf classes; beyond that the proprietary ceiling holds, unless you accept a self-generated taxonomy like the ReactionClassifier's.

### Atom mapping: two different "new" rxnmappers

Two things both get called "the new rxnmapper"; they are different.

**`rxn4chemistry/rxnmapper` 0.4.3 (2026-02-13), MIT — maintenance, same model.** The 0.4.x line is the **same ALBERT model** (`albert_heads_8_uspto_all_1310k`), not a retrain:

| Version | Date | Notable content |
| --- | --- | --- |
| 0.3.1 | 2024-08-27 | Relaxed torch requirement |
| 0.4.0 | 2024-09-19 | Atom-placeholder (`*`) support; better long-reaction errors |
| 0.4.1 | 2025-03-13 | Dropped Python 3.7 from CI |
| 0.4.2 | 2025-06-01 | Removed the `torch<2.1` cap |
| 0.4.3 | 2026-02-13 | Pinned `transformers>=4.0,<5`; install-doc fixes |

Output is unchanged — `{mapped_rxn, confidence}` dicts, `BatchedMapper` for bulk. Worth upgrading only because older versions don't install cleanly on Python 3.11/3.12 (breakage in issues #54/#67/#70 — the reason our fork carries pins); it will not improve mappings.

**`yvsgrndjn/RXNMapper_v2` — the actual retrain.** A genuinely reengineered mapper from the **Reymond group (Yves Grandjean)**, coauthors including Schwaller and Genheden (AstraZeneca), MIT. Default model `alberta-uspto-2800k` (~2.8M USPTO reactions, on HuggingFace); it also bundles the original 2021 model as a selectable option. It **keeps the original API** (`from rxnmapper import RXNMapper`, `get_attention_guided_atom_maps`), so it is a drop-in for Rxn-INSIGHT's `RXNMapper()` call site. Friction:

- **Not on PyPI** — source install only. The dist name is `rxnmapper-v2` but it **imports as `rxnmapper`**, so it collides with the pinned `rxnmapper` package; you install it *instead of* it, not alongside.
- **Heavier, tighter pins:** `transformers==4.46.3` (exact), `torch>=2.4`, `numpy<1.24`, `rdkit>=2024.3.5` — expect resolver work against the fork's environment.
- **No published benchmarks yet.** The cited 2026 ChemRxiv preprint doesn't resolve and the README has no accuracy tables. Actively maintained (pushed 2026-06-29).

**Verdict:** RXNMapper_v2 targets Rxn-INSIGHT's documented weak spot (BE-matrix classification degrades when the mapping fails), so better mappings *plausibly* lift classification — but the gain is unquantified and the packaging/namespace friction is real. **Pilot it in an isolated env; don't swap the production dependency until the preprint lands with numbers** (and ideally a PyPI release). Either way, atom mapping is an input-quality lever, not what sets the label taxonomy.

### Benchmark results

#### ReactionClassifier runs fully offline

The shipped `classify()` path is:

```text
reaction SMILES
  -> RDKit Morgan diff+product fingerprint (radius 2, 2x2048 -> 4096-dim)
  -> 22 MB MLP gate (predicts 1 of 6,962 classes)
  -> RDKit template matching over the predicted class's tier-3 subtree
  -> emit a label only if a shipped template reproduces the recorded product,
     else abstain and expose an (unverified) neural guess
```

- **Dependencies are only `rdkit`, `torch`, `numpy`.** No `transformers`, no `rxnmapper`, no Gemini, no network, **no atom mapping**. The Gemini-3 multi-agent layer wrote the taxonomy and SMIRKS rules *offline, once*; it is not in the inference loop (confirmed from the repo source — the paper abstract is coy about this).
- **Everything needed ships in the wheel (~35 MB):** the gate `model.pt` (22 MB, trained on 628,870 reactions), **54,857 exact `rr0rp1_ring0` templates** across 6,962 classes (`class_to_templates.json`, 12.6 MB), and a 14,060-entry `taxonomy.json`.
- **Two caveats.** The full *generalised*-SMIRKS library is **withheld** — only the exact templates ship, so the generalized-rule layer can't be reproduced or extended. And operational resolution is the **6,962** classes that had training data, not the paper's headline 14,073; the codes are its **own** taxonomy, not RXNO/NameRxn IDs.

#### Throughput, memory, and coverage

All four on the same 1,572 reactions:

| Metric | ReactionClassifier | Rxn-INSIGHT | rxnfp + head | SynCat |
| --- | --- | --- | --- | --- |
| Throughput (rxn/s) | 169.8 | 8.6 | **186.1** | 112.1 |
| Median latency | 2.1 ms | 113 ms | 5.1 ms | — (batch 8) |
| Peak RSS / process | 1,380 MB | 461 MB | 622 MB | **367 MB** |
| Label space | 6,962 own | ~528 named / 10 super | 50 NameRxn | 50 NameRxn |
| Names | structured/descriptive | **eponymous** (Buchwald, Suzuki…) | NameRxn (part eponymous) | NameRxn (part eponymous) |
| Abstains? | yes (template-confirm) | partial (`OtherReaction`) | **no** | **no** |
| Atom mapping | no | **yes** (ALBERT) | no (small BERT fp) | no |
| Accuracy | 58.7% confirmed on ORD¹ | 51.4% named on ORD¹ | 0.994 Schneider² | 0.976 / 0.988 Schneider² |
| Extra deps | rdkit, torch, numpy | + transformers, rxnmapper | + transformers (bert_ft) | + torch_geometric |

¹ Specific-label rate on the ORD sample (abstention / `OtherReaction` counts against it).
² Held-out Schneider-50k accuracy — *not* comparable to the ORD rate; the 50-class models always emit a label, so they have no ORD "coverage" number.

Read of it:

- **Speed splits by architecture, not "ML vs rules."** rxnfp (186) ≈ ReactionClassifier (170) > SynCat (112) ≫ Rxn-INSIGHT (8.6). Rxn-INSIGHT is the outlier because it runs the **ALBERT atom-mapping transformer per reaction** — its documented weak spot and its heavy dependency. Everything else skips atom mapping, which answers the "too heavyweight for ORD-scale" worry. Correcting an earlier assumption: rxnfp is **not** transformer-heavy — `bert_ft` is a *small* BERT (256-dim, vocab 591), so its fingerprint pass is as cheap as an MLP. SynCat's cost is **RDKit featurization**, not the 1.8 MB GNN.
- **Memory: SynCat lightest (367 MB), ReactionClassifier heaviest (1,380 MB).** The RXC bloat is RDKit compiling matched SMIRKS into its template cache (tunable `lru_cache`), not a model — so the earlier prediction that RXC would be memory-light was wrong. Its win is throughput plus simplicity, and memory *per unit throughput* (one process ≈ 20 Rxn-INSIGHT workers). None needs a GPU.
- **Only the "own-taxonomy" models can abstain.** ReactionClassifier withholds a label (and flags low confidence) when nothing fits; Rxn-INSIGHT falls back to `OtherReaction`. The 50-class NameRxn models **cannot** — they force every reaction into one of 50 classes, so they are *confidently wrong* on out-of-scope chemistry (the barbituric row below).

#### Example outputs

Identical input to all four:

| Reaction | ReactionClassifier | Rxn-INSIGHT | rxnfp | SynCat |
| --- | --- | --- | --- | --- |
| Amide coupling | `2.1.2.1` 1° amine + acid → 2° amide | Acylation → acid + primary amine to amide | `2.1.2` Carboxylic acid + amine | `2.1.2` Carboxylic acid + amine |
| Suzuki | `3.1.1.1.1` classic Suzuki (aryl Br + boronic acid) | C-C Coupling → **Suzuki** coupling | `3.1.5` Bromo **Suzuki**-type | `3.1.5` Bromo **Suzuki**-type |
| SNAr / N-arylation | `1.3.5.5` SNAr, heteroaryl halide + 2° amine | → **Ullmann-Goldberg** amine | `1.3.7` Chloro N-arylation | `1.3.7` Chloro N-arylation |
| Nitro reduction | `6.1.11.1` nitrobenzene → aniline | Reduction → nitro → amine | `7.1.1` Nitro to amino | `7.1.1` Nitro to amino |
| Boc protection | `2.4.1.3.1.1` carbamate, amine + dicarbonate | Protection → **Boc** w/ Boc anhydride | `5.1.1` **N-Boc** protection | `5.1.1` **N-Boc** protection |
| Ester saponification | `5.1.4.1.1` cleave methyl/ethyl ester | Deprotection → **saponification** | `6.2.1` CO2H-Et deprotection | `6.2.1` CO2H-Et deprotection |
| ORD SNAr amination | `1.3.6.1` amination of heteroaryl halides | → N-arylation (**Buchwald**/Ullmann) | `1.3.7` Chloro N-arylation | `1.3.7` Chloro N-arylation |
| ORD barbituric condensation | **abstains**; guess `2.1.1.12` conf **0.17** | Heterocycle formation → `OtherReaction` | `2.6.1` Ester Schotten-Baumann ✗ | `6.3.7` Methoxy to hydroxy ✗ |

- **rxnfp and SynCat agree on every clean reaction** (both are Schneider-50k models) and give standard, **RXNO-mappable** NameRxn codes. They diverge only on the out-of-scope barbituric case — where **both are confidently wrong**, in different ways, because neither can abstain.
- **Named reactions, and the Buchwald point.** The NameRxn-50 scheme *does* carry eponymous names (Suzuki, Sonogashira, Stille, Mitsunobu, Williamson, Schotten-Baumann, Fischer-Speier) — but it has **no Buchwald-Hartwig / Ullmann / Heck class**; amine arylations collapse to generic "Bromo/Chloro N-arylation." Only **Rxn-INSIGHT** annotates "Buchwald" here, in its own vocabulary; the discrete Buchwald leaf otherwise lives only in proprietary NameRxn.
- ReactionClassifier lands the **finest, most structured** leaf, but with descriptive rather than eponymous names — and it can **disagree on mechanism** (SNAr vs Ullmann-Goldberg for the N-arylation), a label-quality question worth an audit.

#### What rxnfp and SynCat actually ship

- **rxnfp ships *no* ready-to-run 50-class classifier** — only fingerprint models (`bert_ft`) and a 1k-TPL classifier. Getting the 50 NameRxn labels means computing `bert_ft` fingerprints and **training your own head** (a logistic head over the bundled Schneider fingerprints hit **0.994** here — trivial).
- **SynCat ships a ready-to-run `model_schneider.pt`** (1.8 MB GNN), is **atom-mapping-free**, and its **code + weights are MIT** — the CC-BY-NC concern applies to the *paper*, not the release. It needs only `torch_geometric` (no torch-scatter build) and is the **lightest** of the four. Caveats: it batches internally, its 0.988 headline is Schneider-only, and (like rxnfp) it cannot abstain.

### Crosswalk results: ReactionClassifier → RXNO

#### First, NameRxn ≠ RXNO

- **RXNO** is an open **ontology** (RSC, CC-BY): **653** native reaction terms, opaque IDs (`RXNO:0000140`), **named-reaction-dominated**; generic transforms are delegated to the companion **MOP** ontology or are simply absent.
- **NameRxn** is a proprietary **classifier** that emits `N.N.N` codes *and* the matching RXNO ID (`3.1.1 → RXNO:0000140`); it is the practical labeler for RXNO, but the two are not coextensive (NameRxn ~1,000+ leaves vs RXNO ~653 terms; the code→ID table is proprietary).
- Checked against OLS: Suzuki, Buchwald-Hartwig, Sonogashira, Boc protection, nitro reduction, reductive amination, and Williamson all have RXNO IDs; **"saponification" has none**; **"N-arylation" resolves only to a MOP term**. RXNO covers named reactions richly — it even has Buchwald-Hartwig, which the *open 50-class* NameRxn subset lacks — but skips much generic chemistry.

#### Coverage

| Coverage (of 6,926 classes) | string/synonym match | **LLM pass (47 agents)** |
| --- | --- | --- |
| any RXNO id | 51% | 50% |
| **specific** (non-umbrella) | 15% | **40%** |
| RXNO recall | 116/653 | **243/653** |
| **ORD-weighted specific** | 7% | **38%** |

The naive string matcher collapsed onto broad umbrella nodes (1,165 heterocycle classes → the single "heterocycle synthesis" term); only **7%** of ORD reactions got a *specific* RXNO ID. The **LLM pass** roughly 5x'd that to **38%**, more than doubled RXNO recall, and correctly returned **null** for generic transforms instead of forcing umbrella matches. Sample high-confidence maps: Sonogashira, Buchwald-Hartwig (recovered even from "N-arylation with aryl sulfonates"), Strecker, Appel, Gabriel, piperazine/piperidine/pyrrolidine synthesis, Williamson.

#### Two ceilings

- **Coverage — RXNO's design.** About **48%** of ORD reactions have *no* RXNO term (the LLM confirms null): generic protections, deprotections, redox, and FGI live in MOP or nowhere. No classifier or extra effort changes this; RXNO is named-reaction-only.
- **Quality — unaudited.** The examples show the texture: Suzuki → `RXNO:0000140`, nitro reduction → `RXNO:0000337`, heteroaryl amination → `RXNO:0000372` (all high confidence) — but Boc protection → "N-acylation to carbamate" (medium; a chemist would prefer `RXNO:0000079 Boc protection`) and amide coupling → null. About **55% of the maps are low-confidence** and need review.

### Fallback: RXNO crosswalk of Rxn-INSIGHT names

Kept for the case where you retain Rxn-INSIGHT for its human-readable named reactions and want RXNO IDs bolted on. This is **dominated by the Schneider-50k path** for emitting machine-readable codes (that path yields real NameRxn codes → RXNO directly, no curation), but it remains low-effort and additive if you keep Rxn-INSIGHT:

1. **Curation table** — a versioned data file mapping `rxn_insight_name → RXNO:id` (the 528 SMIRKS names) plus `superclass → RXNO:id` (10 entries). Because both taxonomies trace to Carey 2006 and RXNO's ~500 named reactions overlap Rxn-INSIGHT's 528, most entries are direct matches. An LLM-assisted first pass against the RXNO OWL, plus chemist review, is roughly a day or two. This is the real work — bounded and reviewable, not open-ended.
2. **Schema** — add a nullable `reaction_rxno_id` (and optionally a cached `rxno_label`) to `derived.reaction_classes`. No proto change.
3. **Population** — extend `classify_reaction_smiles` to look up the RXNO ID from the name it already computes. Pure dictionary lookup; no new model call.
4. **Display** — embed RXNO's CC-BY labels/definitions in the UI; link out to OLS.
5. **Honest coverage note** — named reactions get a leaf RXNO ID (~51%), classed-only reactions get a coarse superclass RXNO node (~39%), Miscellaneous gets nothing (~10%). Document this so downstream users don't overread the labels.

## Conclusions / next steps

### Verdict

Two families, and the choice is about *what a label is for*:

- **Want standard, RXNO-mappable NameRxn codes at ORD scale →** SynCat is the standout (ships a model, MIT, atom-mapping-free, lightest RSS, ~112 rxn/s, no head to train); rxnfp is the faster alternative if you'll train the trivial head. Both are capped at **50 classes** and **cannot abstain** — a real limit on ORD's long tail.
- **Want eponymous, human-facing names or fine resolution →** Rxn-INSIGHT (eponymous, but slow and atom-mapping-bound) or ReactionClassifier (6,962 structured leaves, fast, abstains — but its own taxonomy). "Buchwald-Hartwig" as a discrete class needs Rxn-INSIGHT or proprietary NameRxn.

By the resolution you actually need:

1. **~50 NameRxn leaf classes is enough → train/run on Schneider-50k (recommended).** SynCat *ships* a ready-to-run Schneider model; rxnfp needs a trivial head (0.994 here); DRFP trains its own. All emit real NameRxn `N.N.N` codes, all MIT. This is a clean jump from today's 10 Rxn-INSIGHT superclasses to 50 named leaves (plus the superclass/category levels for free by truncating the code), and — because the labels *are* NameRxn codes — it **supersedes the original "crosswalk Rxn-INSIGHT names → RXNO" idea** for emitting machine-readable classes.
2. **Want fine (~1,546 L3), open, near-NameRxn resolution → ReactionClassifier.** Verified hands-on: runs fully offline, ~20x Rxn-INSIGHT's throughput at *higher* specific-label coverage on 1,572 ORD reactions. Practical ceiling is its 6,962 trained classes, and its codes are its own taxonomy.
3. **Need the full ~967 NameRxn leaves with exact codes/RXNO IDs → license NameRxn.** Still the only turnkey path to complete leaf-level coverage.

**RXC→RXNO is the best open path to fine RXNO IDs on the named-reaction slice** — ~38% of ORD reactions get a *specific* RXNO named reaction, well beyond the 50-class NameRxn models, and the draft map already exists. But it is **not** blanket RXNO labeling: ~half of ORD chemistry has no RXNO term, so the right design is **dual-label** — always emit RXC's native code, and attach the RXNO ID where a high-confidence specific match exists.

### This bears on the classification CPU wall

The [full-ORD end-to-end run](../2026-07-02-full-ord-e2e-run-classification-wall/README.md) aborted classification as a multi-day CPU job and deferred it to a GPU. The wall is **Rxn-INSIGHT's per-reaction ALBERT atom-mapping pass, not classification as such** — every alternative benchmarked here is atom-mapping-free and needs no GPU. At the single-process rates measured above, 2,428,291 ORD reactions is roughly **4.0 h** with ReactionClassifier (169.8 rxn/s), **3.6 h** with rxnfp, and **6.0 h** with SynCat, before any parallelism.

Treat that as a lead to test, not a settled result: these rates come from a single process on a dev Mac, whereas the e2e run measured ~0.7 rxn/s of *committed rows* across 4 workers on a `c8i.4xlarge` (shards commit only on completion, so that number undercounts in-flight work). The two are not directly comparable. But the implication is worth checking before buying GPU time: **changing the classifier may be a cheaper fix than provisioning a GPU.**

### Next steps

- **Prototype the Schneider-50k path**: run SynCat (or a trained rxnfp head) over a sample of our reactions, write the 50 `N.N.N` codes (+ names via `rxnclass2name.json`, + RXNO IDs) into a new `derived.reaction_classes` column, and compare labels against the current Rxn-INSIGHT output.
- **Audit ReactionClassifier's label quality at scale.** Offline viability and cost are verified; what's unmeasured is whether its finer codes agree with Rxn-INSIGHT and with chemist judgement (e.g. the SNAr-vs-Ullmann disagreement). If quality holds, it can replace both Rxn-INSIGHT and the crosswalk.
- **Get a chemist review of the medium/low-confidence crosswalk maps** (e.g. Boc → "N-acylation to carbamate" should be `RXNO:0000079`), then decide dual-labeling (native RXC code + RXNO where confident) vs the cheaper SynCat NameRxn path.
- **Pick the granularity target** (10 superclasses → 50 leaves → ~6,962 ReactionClassifier → full ~967 NameRxn). **Decision still open; owner: Steven.** That choice selects the path, and only the last tier needs a paid license.
- **Don't assume RXNO IDs are free.** Public Schneider data has the `N.N.N` codes and names but **not** RXNO IDs. Turning a code into `RXNO:xxxxxxx` needs a crosswalk, most cheaply by matching the NameRxn class *name* (from `rxnclass2name.json`) against the RXNO OWL — a small, bounded lookup step, not automatic. Skip it entirely if you only need NameRxn codes.
- Pilot **RXNMapper_v2** in an isolated env to see if better mappings lift Rxn-INSIGHT classification; keep it out of the production dependency until it has published numbers and a PyPI release.
- Fold the `rxn4chemistry/rxnmapper` 0.4.3 pin bump into the fork as routine hygiene.

## References

- Prior entry: [2026-07-02 Full-ORD end-to-end run](../2026-07-02-full-ord-e2e-run-classification-wall/README.md) (classification CPU wall).
- Benchmark scripts and reproduction guide: [`bench/`](bench/); crosswalk scripts and draft map: [`bench/crosswalk/`](bench/crosswalk/).
- Rxn-INSIGHT: paper <https://pmc.ncbi.nlm.nih.gov/articles/PMC10980627/>, repo <https://github.com/mrodobbe/Rxn-INSIGHT>
- RXNO: OBO Foundry <https://obofoundry.org/ontology/rxno.html>, repo <https://github.com/rsc-ontologies/rxno>, browser <https://www.ebi.ac.uk/ols4/ontologies/rxno>
- NameRxn (NextMove): <https://www.nextmovesoftware.com/namerxn.html>
- Schneider et al., *JCIM* 2015 (50k scheme, NameRxn-labeled): <https://nextmovesoftware.com/blog/2015/02/05/paper-on-reaction-fingerprints-now-out/>
- rxnfp: repo <https://github.com/rxn4chemistry/rxnfp>, paper <https://doi.org/10.1038/s42256-020-00284-w>; 50k results <https://rxn4chemistry.github.io/rxnfp/results_classification_50k/>
- Schneider-50k data (real NameRxn codes): `schneider50k.tsv` + `rxnclass2name.json` <https://github.com/rxn4chemistry/rxnfp/tree/master/data>; paper <https://doi.org/10.1021/ci5006614>
- USPTO-50k (10 superclasses, retrosynthesis): retrosim <https://github.com/connorcoley/retrosim>, GLN <https://github.com/Hanjun-Dai/GLN>
- DRFP: repo <https://github.com/reymond-group/drfp>, paper <https://doi.org/10.1039/D1DD00006C>
- SynCat (2026): paper <https://doi.org/10.1039/D5DD00367A>, repo <https://github.com/phuocchung123/SynCat> (MIT; ships `model_schneider.pt`, atom-mapping-free)
- HuggingFace 10-class model: <https://huggingface.co/pingzhili/chemberta-v2-finetuned-uspto-50k-classification>
- Schwaller ReactionClassifier (2026): paper <https://arxiv.org/abs/2607.01061>, repo <https://github.com/schwallergroup/ReactionClassifier>, PyPI <https://pypi.org/project/reactionclassifier/> (v0.1.0, MIT)
- NameRxn / Pistachio (proprietary, ~967 classes): <https://www.nextmovesoftware.com/namerxn.html>, <https://www.nextmovesoftware.com/pistachio.html>
- rxnmapper: repo <https://github.com/rxn4chemistry/rxnmapper>, PyPI <https://pypi.org/project/rxnmapper/>, paper <https://doi.org/10.1126/sciadv.abe4166>
- RXNMapper_v2: repo <https://github.com/yvsgrndjn/RXNMapper_v2>, model <https://huggingface.co/yvsgrndjn/alberta-uspto-2800k>
- Current ORD usage: `ord-schema/ord_schema/orm/reaction_class.py`, `ord-schema/ord_schema/orm/derived_mappers.py` (`ReactionClasses`)
