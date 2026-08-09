# Structure search over the projection, without the ORM

- **Date:** 2026-08-08
- **Author:** Steven Kearnes
- **Status:** draft (proposal; prototype measured, not built)
- **Tags:** ord-schema, agents, nl-query, duckdb, projection, rdkit, structure-search

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
1.5 GB) with DuckDB 1.5.5 and RDKit, on a 10-core laptop. Scripts are in
[`assets/2026-08-08-structure-search-without-the-orm/`](../assets/2026-08-08-structure-search-without-the-orm/):

- `fp_bench.py` — scan cost at 1M rows, and whether sort order buys pruning.
- `real_bench.py` — screen and verify against real ORD structures.
- `binding_bench.py` — how far reaction-granularity intersection diverges from binding.
- `binding_designs.py` — the two binding designs, measured head to head.
- `fp_precision.py` — screen precision versus fingerprint width, against ground truth.

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
- **D4 — Open: B or E.** Both correct, both fast enough, and the choice is about compiler
  surface rather than speed. B costs a second relation shape and 158 MB; E costs a
  `structure_id` column inside the projection, which cuts against the projection being a
  total restatement of the proto and nothing else. That contract question is the real
  decision and it is not yet made.
- **D5 — Design around verification, not around screening.** It is the dominant cost, it
  cannot be tuned away (finding 3), and it is the natural thing to cache: the structures
  artifact is immutable and deduplicated, so the verified match set for a given canonical
  SMARTS is stable and a repeated query is free.

Similarity search is unblocked by any of this and could ship first: no verification, no
binding subtlety beyond what the IR already does, and an 86 ms scan.

## References

- Prior entries: [2026-08-07 query IR versus generated SQL](2026-08-07-query-ir-versus-generated-sql.md)
  (the IR this extends), [2026-07-31 projection search index](2026-07-31-projection-search-index.md)
  (the artifact-shape argument this reuses),
  [2026-07-30 unlocking agents](2026-07-30-agent-access-sidecars-or-orm.md).
- PRs: [ord-schema#947](https://github.com/open-reaction-database/ord-schema/pull/947)
  (projection/view parent-child derivation),
  [ord-schema#948](https://github.com/open-reaction-database/ord-schema/pull/948) (the query IR),
  [ord-schema#949](https://github.com/open-reaction-database/ord-schema/pull/949) (schema description).
- Scripts and raw output:
  [`assets/2026-08-08-structure-search-without-the-orm/`](../assets/2026-08-08-structure-search-without-the-orm/).
- DuckDB bit functions (`bit_count`, `get_bit`, `&` on `BITSTRING`):
  <https://duckdb.org/docs/stable/sql/functions/bitstring>.
- RDKit fingerprints used for screening: <https://rdkit.org/docs/RDKit_Book.html#pattern-fingerprints>.
