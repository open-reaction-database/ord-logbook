# Structure search over the projection, without the ORM

- **Date:** 2026-08-08
- **Author:** Steven Kearnes
- **Status:** in progress (structures artifact and projection ids shipped in [ord-schema#956](https://github.com/open-reaction-database/ord-schema/pull/956); the query predicate and executor are not yet built)
- **Tags:** ord-schema, agents, nl-query, duckdb, projection, rdkit, structure-search
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

The query IR that shipped in [ord-schema#948](https://github.com/open-reaction-database/ord-schema/pull/948)
compiles a model-emitted `Query` to DuckDB SQL over the projection. It has no structure
operator at all — no substructure, no similarity — which is the most important query class
in chemistry and the one thing the ORM's RDKit cartridge does well.

Worse, the omission fails quietly. Asked for "reactions with a pyridine ring," a model
reaches for the only tool the grammar offers:

```sql
-- compiles cleanly; chemically meaningless
... e0 -> contains(e0.smiles, 'c1ccncc1') ...
```

SMILES substring is not substructure. So: can structure search run against the projection
directly, making the ORM unnecessary for search, and what does the predicate look like?

## Summary

**Yes, and it needs no index.** Parquet has no GiST and cannot get one, but it does not
need one: the corpus holds only **763,673 distinct input structures** behind 11.5M
component rows, and DuckDB screens all of them with a bitwise fingerprint `AND` in
**~250 ms**. The GiST index exists because Postgres is row-oriented and cannot scan a
million molecules; a columnar artifact can. Similarity search needs nothing further —
Tanimoto is *defined on* the fingerprint, so an **86 ms** scan is the whole answer.

Three findings then shape the predicate, and two of them overturned the design I started
with:

1. **Verification is irreducible.** Screen precision is 14–56% and **plateaus by 2048
   bits** — 8× wider fingerprints buy nothing. The false positives are not collisions;
   they are the gap between feature containment and subgraph isomorphism. No fingerprint
   choice, hashed or not, removes the exact-match step.
2. **Reaction-granularity intersection is unusable.** Resolving a structure predicate to a
   set of reaction IDs and intersecting with the rest of the query over-returns by
   **94%** on `pyridine + SOLVENT`. Element binding is mandatory, not a refinement.
3. **DuckDB forbids subqueries inside lambdas**, which is where element binding lives. Two
   designs get around it and both are correct; neither is performance-critical, because
   verification costs 20–500× more than either.

## Method

Everything ran against the local corpus projection (53 datasets, 2,428,291 reactions,
1.5 GB) with DuckDB 1.5.5 and RDKit, on a 10-core laptop. Scripts sit beside this
entry:

- `fp_bench.py` — scan cost at 1M rows, and whether sort order buys pruning.
- `real_bench.py` — screen and verify against real ORD structures.
- `binding_bench.py` — how far reaction-granularity intersection diverges from binding.
- `binding_designs.py` — the two binding designs, measured head to head.
- `fp_precision.py` — screen precision versus fingerprint width, against ground truth.
- `verify_narrowing.py` — whether the query's other predicates shrink the verification
  set.

Fingerprints are RDKit `PatternFingerprint` for substructure screening and Morgan for
similarity, stored as fixed-width `BLOB` and read back with `CAST(fp AS BITSTRING)`.

## Findings

### 1. The scan is affordable, so the index is unnecessary

Parquet's only index-like structures are row-group min/max statistics, optional Bloom
filters (equality only), and column pruning. None accelerates bit containment or Tanimoto.
None is needed:

| operation | cost | note |
| --- | --- | --- |
| substructure screen, 763K real structures | 211–298 ms | full scan |
| substructure screen, 1M synthetic | 55 ms | full scan |
| similarity, full Tanimoto, 1M | 86 ms | no verification step exists |
| popcount-band pruning via sort order | 48 ms vs 53 ms | real but marginal |
| featurize 763,673 structures | 15.7 s | 10 cores |
| artifact size | 37 MB per 200K | both fingerprints, zstd |

Sorting by Morgan popcount lets row-group statistics bound the Tanimoto band
(`popcount(B) ∈ [t·popcount(A), popcount(A)/t]`). It is free at write time and worth
doing, but it is not load-bearing — the scan is already cheap enough that the pruning
barely registers.

**Similarity needs no RDKit at query time and no verification**, because the fingerprint
is not a proxy for the answer. Substructure is the hard case, and the rest of this entry
is about it.

### 2. Dedup is local enough to keep the per-dataset artifact model

Global dedup gives 763,673 distinct input SMILES; summing per-dataset distinct counts
gives 1,068,897 — only **28% worse**. A `structures` artifact can therefore stay
per-dataset, a child of `projection` exactly as `view` is, inheriting the parent and
staleness machinery from [ord-schema#947](https://github.com/open-reaction-database/ord-schema/pull/947)
without change. Nothing forces a corpus-wide artifact with its own build path and its own
staleness rules.

### 3. Verification is irreducible, and wider fingerprints do not help

Ground truth computed by verifying all 763,673 structures against each SMARTS, then
screening at increasing widths (survivors, and precision against ground truth):

| query | true hits | 1024 | 2048 | 4096 | 8192 | 16384 |
| --- | --- | --- | --- | --- | --- | --- |
| pyridine | 143,999 | 22% | 25% | 25% | 25% | 25% |
| carboxylic acid | 72,370 | 14% | 14% | 14% | 14% | 14% |
| boronic acid | 8,327 | 30% | 37% | 46% | 47% | 48% |
| sulfonamide | 32,340 | 48% | 55% | 56% | 56% | 56% |

Precision plateaus by 2048 bits. At 16384 bits over 763K structures collisions are rare,
and precision is still 14–56%, so **the residual false positives are structural, not
collisional**: a molecule can contain every path and environment of pyridine without
containing a pyridine ring, and SMARTS constraints like `[OH]`, `[NX3;H2]`, ring
membership, and bond order are not representable in a path fingerprint at all.

This bears directly on non-hashed fingerprints, which eliminate collisions by
construction. The measurement bounds what that is worth: roughly 3 percentage points for
pyridine, more for boronic acid, and in every case still far from exact. The cost is
sparse storage and a set-containment test per row instead of a fixed-width `AND`. Not a
good trade, and — importantly — it does not remove the verification step, which is what
one would hope to buy.

Verification itself is fast and parallel: **18,477 structures/s on one core, 117,410/s on
ten**. Pyridine's 577,105 survivors verify in 4.34 s; boronic acid's 22,215 in 0.79 s.
Because the structures artifact is deduplicated 15:1 against component rows, that cost is
already amortized across the corpus.

### 4. Reaction-granularity intersection over-returns catastrophically

The simplest design resolves a structure predicate to a set of matching SMILES, converts
it to a set of reaction IDs, and composes with the rest of the query by set algebra. It
cannot bind an element, so `structure(pyridine) AND role = SOLVENT` becomes "contains a
pyridine-ish component" ∩ "contains some solvent" — possibly different components:

| query | bound (correct) | intersected | over-returns |
| --- | --- | --- | --- |
| pyridine + SOLVENT | 25,805 | 432,060 | **94.0%** |
| carboxylic acid + SOLVENT | 60,572 | 402,199 | **84.9%** |
| boronic acid + REACTANT | 130,219 | 132,600 | 1.8% |

The third row looks acceptable only because nearly every reaction has *some* reactant, so
the intersection adds almost nothing. This is exactly the failure the IR's quantifiers
were designed to prevent, reintroduced for structure predicates. It disqualifies the
design.

### 5. Element binding: two designs, both correct, neither the bottleneck

DuckDB rejects `subqueries in lambda expressions are not supported`, so a structure
predicate cannot semi-join against the match set where binding lives. Two ways around it,
measured on identical queries:

- **B — materialize the component relation.** One row per component, the component struct
  preserved whole. Binding is implicit: a row *is* an element. Nested paths resolve
  identically (`c.amount.volume_liters`), so the expression compiler is shared and only
  the binding mechanism changes. **11.5M rows, 158 MB, built in 4.9 s.** This is the
  `UNNEST` the design refuses at query time, paid once at build time.
- **E — dense structure ids plus a bitmap parameter.** Give each distinct structure a
  dense id, carry it on each component, and pass the match set as a `BITSTRING`. The test
  becomes `get_bit($m, e.structure_id)` — a scalar expression, legal inside a lambda. The
  bitmap for 763K structures is **746 KB**, built in 39 ms. No second relation shape, no
  join.

Both return identical answers (25,805 and 130,219). B runs in 8–10 ms, E in ~182 ms.

The gap is real but irrelevant: verification costs 4.34 s for the same query, **24× E and
500× B**. The binding mechanism is at most 2% of the query. This choice is therefore an
architecture decision about how many relation shapes the compiler targets, not a
performance decision, and it should be argued on that basis.

There is also a fully general form of E worth recording even though nothing needs it yet:
give every **element of a repeated field** a unique address — `(reaction_id, path,
ordinal)`, or a dense id enumerating that repeated level corpus-wide — rather than giving
ids only to distinct structures. Any externally-evaluated predicate (a structure match, a
learned model scoring components, a property lookup against an outside database) could
then return a set of *element* addresses, and composition with the rest of the query
stays plain set intersection at element granularity instead of the reaction granularity
finding 4 disqualifies. Structure ids are the cheap specialization: a substructure match
is a property of the structure alone, so 763K structure ids do the work of 11.5M element
addresses, and the match set compresses to a 746 KB bitmap. The general address only
earns its cost when a predicate's answer varies *per occurrence* rather than per
structure — and an address must carry its repeated level, so that `inputs.components`
addresses never intersect with `outcomes.products` addresses.

### 6. The query's other predicates collapse the verification set

Verification only has to consider structures that could change the answer. When a
quantifier constrains the same element with scalar predicates, only structures that
survive the screen *and* occur in an element passing those predicates need verifying:

| scenario | screen survivors | narrowed | ratio | verify eager → narrowed |
| --- | --- | --- | --- | --- |
| pyridine, unconstrained | 577,105 | 577,105 | 1× | 4.45 s → 4.46 s |
| pyridine, as SOLVENT | 577,105 | 370 | 1,560× | 4.50 s → 0.57 s |
| pyridine, SOLVENT > 5 mL | 577,105 | 136 | 4,243× | 4.50 s → 0.56 s |
| carboxylic acid, as REAGENT | 505,653 | 109 | 4,639× | 3.90 s → 0.56 s |
| boronic acid, REACTANT > 1 mmol | 22,215 | 398 | 56× | 0.81 s → 0.57 s |

Only ~370 distinct structures are ever used as solvents and screen positive for pyridine.
The 0.56 s floor is process-pool spawn, not matching — a persistent worker pool turns the
narrowed cases into milliseconds. Narrowing is sound only for conjuncts in the same
quantifier scope: under `or` or `not` it would change the answer, so those fall back to
eager verification — a rule in the same style as the compiler's existing ones.

The remaining eager cost also shrinks if the artifact carries serialized molecules:
verifying from `Mol.ToBinary()` blobs instead of re-parsing SMILES runs at **93,095
structures/s on one core versus 18,812** (4.9×), for ~327 B/structure — roughly 250 MB
corpus-wide. That prices the worst case (an unconstrained pyridine-class query) at well
under a second on ten cores.

## Conclusions / next steps

- **D1 — No GiST-like index, and none is needed.** Parquet cannot express one; a columnar
  full scan over 763K distinct structures costs ~250 ms. Sort by Morgan popcount anyway
  because it is free, but do not build machinery around it.
- **D2 — A `structures` artifact, per-dataset**, child of `projection` alongside `view`:
  canonical SMILES, pattern fingerprint, Morgan fingerprint, Morgan popcount. Roughly
  150 MB and 16 s of featurization for the whole corpus. Dedup locality (finding 2) is
  what lets it stay per-dataset.
- **D3 — Element binding is mandatory.** Finding 4 rules out reaction-granularity
  intersection outright; 94% wrong on a natural query is not a tradeoff.
- **D4 — Resolved: E.** Both designs are correct and both are fast enough, so the choice
  was about compiler surface rather than speed. E's cost is one opaque integer column on
  each structure-bearing element inside the projection — derived data in the same sense
  as the precision columns admitted in
  [ord-schema#947](https://github.com/open-reaction-database/ord-schema/pull/947) —
  whereas B forks the compiler's target model into two relation shapes permanently. The
  general element address (finding 5) is the future-proof form of E; nothing yet
  justifies its cost over structure ids.
- **D6 — Rewrite SMARTS with explicit hydrogens; refuse only what cannot be rewritten.**
  The artifact stores molecules built from SMILES, so their hydrogens are implicit and an
  explicit-H pattern matches almost nothing: the query returns empty and says nothing
  about why. `MergeQueryHs` folds the hydrogens into heavy-atom H-count constraints, and
  the folded form matches — measured, `[H]OC` becomes `[O&!H0]C`, which both matches
  methanol and screens for it. So the pattern is rewritten and a warning issued, rather
  than refused. A hydrogen the merge cannot fold — isotopic (`[2H]`), or with no heavy
  neighbor (`[H][H]`) — survives as an atomic-number-1 atom and *is* refused, because
  folding it would silently drop the isotope constraint and change what the pattern means.

  **Correction (2026-08-08).** This entry first claimed explicit-H patterns break the
  screen's completeness — that `[H]OC` fails the fingerprint screen against methanol
  "even though the merged query matches it." That comparison was between two different
  queries. Measured properly, `[H]OC` against methanol gives `match=False, screen=False`:
  the screen and the exact match agree, and across 221 explicit-H query/target pairs the
  screen rejected **zero** true matches. The completeness invariant in finding 1 holds
  without exception; the hazard is the empty result described above, not a false
  negative.
- **D7 — Standardization is deferred, deliberately.** Canonical tautomers and protonation
  states affect SMILES, fingerprints, and serialized molecules alike — a query for the
  neutral amine should arguably find the hydrochloride salt's cation. That is a
  corpus-standardization question, not a predicate-design question, and it gets its own
  entry once this work lands.
- **D5 — Design around verification, not around screening.** It is the dominant cost and
  it cannot be tuned away (finding 3), but it can be collapsed: narrow by the query's
  sibling conjuncts (finding 6, up to 4,639×), verify from serialized molecules rather
  than SMILES (4.9×), keep a persistent worker pool, and cache the verified match set
  keyed by `(artifact version, canonical SMARTS)` — the artifact is immutable and
  deduplicated, so a repeated query is free.

Substructure is the priority; similarity falls out of the same artifact for free (an
86 ms scan with no verification step) but is not the driver.

## References

- Prior entries: [2026-08-07 query IR versus generated SQL](../2026-08-07-query-ir-versus-generated-sql/README.md)
  (the IR this extends), [2026-07-31 projection search index](../2026-07-31-projection-search-index/README.md)
  (the artifact-shape argument this reuses),
  [2026-07-30 unlocking agents](../2026-07-30-agent-access-sidecars-or-orm/README.md).
- PRs: [ord-schema#947](https://github.com/open-reaction-database/ord-schema/pull/947)
  (projection/view parent-child derivation),
  [ord-schema#948](https://github.com/open-reaction-database/ord-schema/pull/948) (the query IR),
  [ord-schema#949](https://github.com/open-reaction-database/ord-schema/pull/949) (schema description).
- Scripts and raw output: beside this entry.
- DuckDB bit functions (`bit_count`, `get_bit`, `&` on `BITSTRING`):
  <https://duckdb.org/docs/stable/sql/functions/bitstring>.
- RDKit fingerprints used for screening: <https://rdkit.org/docs/RDKit_Book.html#pattern-fingerprints>.
