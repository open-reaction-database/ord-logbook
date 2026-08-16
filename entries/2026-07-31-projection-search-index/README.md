# Does the projection need a search index?

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **Status:** draft (one decision open: does the fact table replace the projection?)
- **Tags:** ord-data, ord-schema, parquet, duckdb, agents, indexing, design

## Question

[The agent-access entry](../2026-07-30-agent-access-sidecars-or-orm/README.md) settled on a total
nested projection of the `Reaction` proto. The obvious follow-on: nested lookups like
"reactions where an input is named THF" are the most common shape an agent will ask, and
they traverse three repeated levels. Are they fast enough, and if not, should a flat
fact table — one row per value, keyed back to its reaction — be published alongside?

That table would be the same shape as the ORM's `derived.*` schema, so the question is
really whether the sidecar design needs the same two-layer split Postgres has.

## Summary

**Yes — and possibly instead of the projection rather than alongside it.** That last
part is the open question; everything else here is measured.

Three claims this entry set out to make did not survive their own measurements, so read
the findings rather than the intuitions: nested queries are not slow, a fact table is not
worse at wide analysis, and the two artifacts are not a chain.

The performance premise turned out to be wrong. Nested lookups looked catastrophic — a
full-corpus "input named THF" did not finish in four minutes — but that was the *query
plan*, not the format. `UNNEST` in the `FROM` clause materializes exploded rows;
`list_transform` / `list_filter` lambdas scan the child arrays. Same answers, **27–200×
apart**, and the lambda form does the full corpus in **0.90 s**. So speed alone does not
justify a second artifact.

**Ergonomics does.** The fast idiom is the non-obvious one. An agent reaching for
`UNNEST` — the form every tutorial teaches — gets the plan that does not finish, against
a 393-leaf schema. The same question against six flat columns is
`WHERE role='INPUT' AND identifier_type='NAME' AND identifier_value='THF'`, which any
consumer writes correctly first try. The
[agent-access entry](../2026-07-30-agent-access-sidecars-or-orm/README.md) argued that nested
Parquet is easier for a model to query than normalized tables; on this evidence that
holds against 71-table joins but not against a flat fact table.

Measured, that table is
`(reaction_id, role, component_index, smiles, identifier_type, identifier_value)` —
**17,021,402 rows, 186.2 MB, 8.7 minutes**, **13× faster** on this query class at **15%**
of the projection's size, reconstructing co-membership by self-join on the entity key in
0.070 s.

The textbook objection to a fact table standing alone does not survive contact with this
corpus. Entity-attribute-value shapes are supposed to be poor at wide projection —
correlating yield with temperature with catalyst becomes a self-join per attribute. On
ORD they are *faster*: 0.015 s against 0.044 s for two attributes, 0.030 s against
0.052 s for three, 0.023 s against 0.045 s for a bucketed aggregate, with identical
answers. ORD is sparse, so a fact table stores only populated values and each predicate
touches a dense slice, while the columnar form scans 2.43M rows of mostly-null columns.

A *total* EAV — one row per populated leaf, carrying a positional `entity_key` — costs
732.8 bytes per reaction on USPTO against the raw projection's 809.8 (and the normalized
projection's 629.6; the EAV prototype is un-normalized, so the fair comparison is the
first pair). It is therefore plausible that a normalized fact table could replace the
projection outright rather than accompany it. That is measured only on two datasets and
un-normalized, and it is the open question this entry does not close.

Two corrections to the record fall out. Neither artifact derives from the other — both
read the source protos, so they are peers rather than a chain — and the "structural
explosion is expensive" claim in the agent-access entry was measuring `UNNEST`, not
nesting.

## Method

Measured against the normalized total projection of `ord-data` `main` at `e017725`
(2,428,291 reactions, 1,240.7 MB), the tier-1 views from
[ord-schema#914](https://github.com/open-reaction-database/ord-schema/pull/914), and a
fact table built for this entry. DuckDB 1.5.5, single laptop process, cold.

The fact table is built by
[`component_facts.py`](component_facts.py),
reading source protos through `parquet.iter_reactions` — *not* the projection. It emits
one row per non-structural identifier per component, carrying the canonical `smiles`
alongside, and one row for components that have no non-structural identifier at all, so
no component is invisible.

`role` is `INPUT` for `reaction.inputs[*].components` and `OUTPUT` for
`reaction.outcomes[*].products`. `component_index` is assigned over inputs in sorted key
order then outcomes, which makes it stable across rebuilds without encoding the full
path.

## Findings

### 1. The query plan, not the nesting, was the problem

Identical predicates, identical answers, written two ways:

| scope | `UNNEST` in `FROM` | list lambdas | ratio |
| --- | ---: | ---: | ---: |
| 200 reactions | 0.062 s | 0.001 s | 62× |
| 1,000 reactions | 0.286 s | 0.002 s | 143× |
| 5,000 reactions | 1.601 s | 0.008 s | 200× |
| 40,000 USPTO rows, count `SMILES` identifiers | 5.264 s | 0.198 s | 27× |
| full corpus, input named "THF" | did not finish in 4 min | **0.90 s** | — |

Both forms agree exactly at every scale (33 / 164 / 884 on the slices; 172,274 on the
40k count). `UNNEST` in the `FROM` clause materializes the exploded intermediate —
8.3 rows per reaction here — while the lambda form scans the list child arrays in place
and never builds it.

This matters beyond a benchmark: an agent writing SQL will reach for `UNNEST`, because
that is the idiom every tutorial teaches. The published schema documentation has to say
so explicitly, or the artifact will be judged 200× slower than it is.

### 2. The projection is sub-second on the queries that motivated the question

Full corpus, nested projection, lambda form:

| query | wall-clock | matches |
| --- | ---: | ---: |
| input named "THF" | 0.90 s | 145,285 |
| input with `smiles = 'C1CCOC1'` | 0.78 s | 320,789 |
| output with `smiles = 'C1CCOC1'` | 0.74 s | 10 |
| same component: named THF **and** volume > 5 mL | 0.80 s | 91,683 |

The last row is the one that decides the design question. Conjunction *within a single
component* — the predicate that a reaction-keyed flat table cannot express, because it
cannot tell whether two facts describe the same component — runs natively here, at the
same cost as the single-predicate version. In the nested form co-membership is
structural; nothing has to be reconstructed.

### 3. The fact table wins on selection, at 15% of the size

| | rows | size | build |
| --- | ---: | ---: | ---: |
| nested projection | 2,428,291 | 1,240.7 MB | 20.3 min |
| component fact table | 17,021,402 | **186.2 MB** | 8.7 min |

| query | projection | facts |
| --- | ---: | ---: |
| input named "THF" | 0.90 s | **0.068 s** |
| input `smiles = 'C1CCOC1'` | 0.78 s | **0.052 s** |
| output `smiles = 'C1CCOC1'` | 0.74 s | **0.031 s** |
| top 5 input names | — | 0.071 s |

Roughly **13× faster at 15% of the size** — though this slice covers component
identifiers only, so it is not a like-for-like size comparison with the whole projection.
The `component_index` key earns its place: it
reconstructs co-membership by self-join in **0.070 s**, no worse than the single-predicate
query, and it distinguishes two questions that are otherwise indistinguishable — "one
component that is both X and Y" versus "one reaction containing an X and a Y." Joining on
`reaction_id` alone silently answers the second when the first was meant. Measured, the
THF/DMF form of the second returns 5,021 reactions in 0.088 s.

### 3b. The expected weakness — wide projection — is not there

A fact table is supposed to lose at multi-attribute analysis, because each attribute
costs a self-join where a columnar layout costs one more column read. Measured against
the tier-1 view and a reaction-scalar fact table (2,764,347 rows, 54.1 MB) holding the
same five columns:

| query | columnar | facts | answer |
| --- | ---: | ---: | ---: |
| 2 attributes | 0.044 s | **0.015 s** | 48,654 |
| 3 attributes (2 self-joins) | 0.052 s | **0.030 s** | 18,334 |
| yield bucketed by temperature | 0.045 s | **0.023 s** | 44 buckets |

The fact table wins every one. The reason is sparsity: only `reaction_id`,
`reaction_smiles`, `input_smiles` and `output_smiles` are near-total in this corpus, and
`conversion_percent` and `pressure_kilopascals` are populated on 0.2% and 0.3% of rows.
The columnar form scans 2,428,291 rows regardless; the fact table stores only what
exists, so a predicate on `pressure_kilopascals` touches 7,026 rows rather than skipping
2.4M nulls. Classic EAV advice assumes dense attributes, and ORD is not dense.

Absence is also better represented. A fact table distinguishes "measured zero" from "not
measured" by the presence of a row, where the columnar form needs a nullable column and
the convention that null means the source is silent.

### 4. The two artifacts are peers, not a chain

An earlier reading of this had the fact table derived *from* the projection, with the
projection's version stamp guarding staleness. That is not what the prototype does and
not what it should do: it reads source protos directly, so both artifacts are independent
tier-1 projections of the same authority.

That is the better arrangement. Neither imposes a rebuild ordering on the other, each is
independently verifiable against the source, and consistency comes from sharing
`message_helpers.smiles_from_compound` rather than from a derivation chain. The evidence
is that three independently built artifacts — the tier-1 view, the nested projection, and
the fact table — return **identical** answers for the same structural queries: 320,789
inputs and 10 outputs matching THF, and 145,285 for the name query where both the
projection and the facts can express it. Three-way agreement across separately written
code paths is a stronger correctness signal than a derivation chain would have provided.

### 5. Publishing a second artifact needs a demonstrated need, and there is not one yet

This repo has already made this decision once. Finding 9 of the sidecar entry retired a
sorted "compacted view" after measuring that projection pushdown already made the
unsorted form fast enough, on the reasoning that a second published artifact carries its
own staleness, stamping, and verification surface.

The same reasoning applies, and the numbers are less favourable to the index than they
first looked: the artifact it would accelerate answers in 0.9 s, the acceleration is
13× on one query class, and nothing user-facing has yet been shown to need it. Ship the
projection; keep the fact table as a measured, reproducible recipe. If a UI backing
interactive structural search lands, or query telemetry shows component predicates
dominating, 186 MB and 8.7 minutes is a cheap answer waiting to be published.

## Conclusions / next steps

- **D1 — Publish a fact table, not only the projection.** It is faster on selection (13×)
  *and* on wide analysis (2–3×), and the sparsity that makes the second true is a
  property of this corpus rather than of the query.
- **D2 — Settle whether the fact table replaces the projection before publishing either.**
  The un-normalized total EAV already undercuts the raw projection on USPTO bytes, so the
  two-artifact plan may be one artifact too many. What is needed is a normalized total
  EAV over the full corpus, measured for size, build time, and the same query set — the
  prototypes beside this entry do two datasets un-normalized. **This is the open decision; the
  rest of this log is contingent on it.**
- **D3 — Document the `UNNEST` trap wherever the nested form ships.** A consumer reaching
  for the idiomatic form gets 27–200× worse performance and will conclude the artifact is
  unusable. This is a documentation obligation, not a footnote — and it is an argument
  *for* the flat shape, whose obvious query is also its fast one.
- **D4 — Carry an entity key, whatever ships.** Reaction-level keying alone cannot express
  intra-component conjunction, and answers a different question without saying so. The
  cheap form is an integer index per component; the full form is a positional
  `entity_key` that also preserves ordering.
- **D5 — Derive everything from the source protos.** Peers, not a chain, sharing the
  canonicalization helpers. The three-way agreement in finding 4 is what this buys.

Open, and load-bearing: whether the projection survives at all. Its remaining advantages
over a total fact table are a self-documenting schema and a natural retrieval shape — and
retrieval is already served by the source `reaction` column, joinable on `reaction_id`.
If a normalized total EAV lands near the projection's size, the honest conclusion is one
artifact, not two, and [the agent-access entry's](../2026-07-30-agent-access-sidecars-or-orm/README.md)
D4 needs revisiting rather than extending.

## References

- Prior entries: [2026-07-30 unlocking agents](../2026-07-30-agent-access-sidecars-or-orm/README.md)
  (the projection decision this refines),
  [2026-07-25 derived parquet sidecars](../2026-07-25-derived-parquet-sidecars/README.md)
  (finding 9, the precedent for refusing a second artifact).
- ORM shapes this mirrors: `ord-schema` `ord_schema/orm/derived_mappers.py`
  (`CompoundSmiles`, `ProductCompoundSmiles` — entity-keyed derived facts, split by role
  because the foreign keys point at different parents), `ord_schema/orm/rdkit_mappers.py`
  (`RDKitMols`, role-agnostic and deduplicated by SMILES).
- Fact-table builder and query scripts:
  [`ASSETS.md`](ASSETS.md).
- DuckDB list lambdas (`list_transform`, `list_filter`, `flatten`):
  <https://duckdb.org/docs/stable/sql/functions/lambda>.
