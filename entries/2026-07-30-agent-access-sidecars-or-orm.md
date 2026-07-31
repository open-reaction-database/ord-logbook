# Unlocking agents: tabular sidecars, the ORM, or both

- **Date:** 2026-07-30
- **Author:** Steven Kearnes
- **Status:** draft (recommendation settled; scope of the expansion open)
- **Tags:** ord-data, ord-schema, ord-interface, parquet, duckdb, agents, orm, rdkit,
  design, data-contracts

## Question

[The sidecar entry](2026-07-25-derived-parquet-sidecars.md) shipped eleven flat columns
per reaction. Before that lands, the obvious next question: how far should the sidecars
go? If they could reproduce what the ORM does, we could stop populating the ORM
altogether and point DuckDB at files instead. That raises three sub-questions worth
separating, because they have different answers:

1. Is reproducing the ORM's functionality in tabular sidecars *feasible*?
2. Does the proto's nesting force an interface like GraphQL on us?
3. Is any of this the right goal — or is full access to the existing ORM the actual path
   to unlocking agents?

## Summary

**Expand the sidecars; do not reproduce the ORM; do not build GraphQL.**

The ORM's shape is not the data's shape. `ord_schema/orm/mappers.py` walks the proto
descriptors and emits **71 tables**, using single-table inheritance throughout because
Postgres cannot express "a `Time` appearing twice inside a `ReactionInput`." Parquet
nests natively, so porting that normalization would mean carrying a workaround for a
constraint the target does not have — and handing agents 71-way joins to get right.

The one capability that genuinely belongs to Postgres is the RDKit cartridge, and the
measurement that decides this entry is that **ORD does not need it.** The corpus holds
**1,432,318 distinct component structures**. With pattern fingerprints precomputed, a
full substructure scan over all of them costs **~1–2 seconds single-threaded with no
index at all**, and a Tanimoto scan costs **0.76 s**. GiST indexes exist to make this
tractable at 10⁸ molecules; at 10⁶ the brute-force scan is already interactive.

Nesting is not the problem either. DuckDB reads nested Parquet directly — `unnest` over
14.1M list elements in the current sidecars returns in **0.11 s**. GraphQL solves
over-fetching across a network boundary, and the entire point of the sidecar design is
that there is no boundary: the consumer reads columns off disk and projection pushdown
*is* the "ask only for what you need" mechanism. Adding GraphQL would reintroduce the
server the design exists to avoid.

Versioned SQLite packages were considered as the alternative container and measured
head-to-head (finding 6): **10.9× the bytes and 10–88× slower** on the analytical scans
that define the unserved mode, in exchange for point lookups Parquet cannot match. The
workload decides it, and the workload here is scans.

On the third question, the honest answer is that the two paths serve different modes and
only one of them is currently unserved:

- **Mediated** — "find me reactions like X." Already built. `nl_query.py` translates free
  text into structured `QueryParams` and deliberately never emits SQL. An MCP wrapper
  over it is small, useful work.
- **Open-ended** — "correlate yield with temperature across Pd catalysts," "build me a
  training set." No fixed predicate set covers this, and the existing API caps every
  result at **`MAX_RESULTS = 1000`** rows. An agent doing analysis cannot get its data
  out at all.

So they are complementary rather than competing, and the sidecars are the half that is
missing. **The ORM becomes the website's backend; the sidecars become the agent
surface.** Whether the ORM is worth keeping after that is a separate decision this entry
does not force.

## Method

Measured against `ord-data` `main` at `e017725` (53 parquet datasets, 2,428,291
reactions) and the tier-1 views produced by `ord_schema.views.write_view` at
[ord-schema#914](https://github.com/open-reaction-database/ord-schema/pull/914).
Sizes are decimal — MB is 10⁶ bytes.

ORM and query-surface claims were read from `ord-schema` `ord_schema/orm/` and
`ord-interface` `ord_interface/api/` on `main`. Table count is
`len(Base.metadata.tables)` after importing `mappers`, not an estimate.

Structure-search costs were measured on the distinct component SMILES extracted from the
tier-1 views, sampled at the first 100,000 and projected to the full 1,432,318 by ratio.
The search mirrors what the cartridge does internally: a pattern-fingerprint screen
(bitwise superset test, vectorized in numpy) followed by exact
`HasSubstructMatch` verification on the survivors. Projections are linear in structure
count, which is the right model for a screen-then-verify scan and conservative for the
screen, whose cost is pure bandwidth.

DuckDB figures are single queries against `views_out/*.parquet` on a laptop, DuckDB
1.5.5, cold process. The SQLite comparison in finding 6 loads the same views into a
`reaction` table plus a normalized `component` table (14.1M rows), with indexes on
component SMILES, component `reaction_id`, and yield; queries run against a read-only
connection in a fresh process. Both formats therefore carry identical data.

## Findings

### 1. The ORM's 71 tables are a Postgres artifact, not a data shape

`mappers.py` generates one table per proto message type. Its own docstring gives the
reason: some message types appear more than once in a parent (`Time` in `ReactionInput`),
and some are repeated while others are unique, which together force an inheritance
strategy. The module picks single-table inheritance for *all* message types "for
convenience and consistency," explicitly noting that this means uniqueness constraints
are not enforced in the database.

That is a well-made decision for a relational target. It is also entirely a response to
relational limitations. Parquet has `STRUCT`, `LIST`, and `MAP`; a `ReactionInput`
holding two `Time` fields is one struct with two fields, needing no inheritance, no
discriminator column, and no join. Reproducing the 71-table decomposition in Parquet
would carry the workaround without the constraint that motivated it.

It would also be worse for the consumer this design exists to serve. A model writing
SQL against 71 normalized tables gets joins wrong; a model reading
`unnest(inputs).components` does not.

### 2. The query surface is seven predicates, and five are already flat

`ord_interface/api/queries.py` defines seven `ReactionQuery` subclasses:

| query | needs RDKit? | served by the current tier-1 view? |
| --- | --- | --- |
| `DatasetIdQuery` | no | yes |
| `ReactionIdQuery` | no | yes |
| `ReactionYieldQuery` | no | yes |
| `ReactionConversionQuery` | no | yes |
| `DoiQuery` | no | yes |
| `ReactionComponentQuery` | **yes** — `@>`, `%`, `qmol` | EXACT only |
| `ReactionSmartsQuery` | **yes** — `reaction_from_smarts` | no |

Eleven columns already cover five of seven. `ReactionComponentQuery`'s EXACT mode is a
canonical-SMILES equality test — `rdkit.mols.smiles = %s` with `Chem.CanonSmiles` applied
to the pattern — which the view's canonicalized component columns answer directly. What
is genuinely missing is SUBSTRUCTURE, SIMILAR, SMARTS, and reaction-level SMARTS.

### 3. ORD is small enough that structure search needs no index

This is the finding the entry turns on. The tier-1 views hold 14.1M component SMILES
occurrences over 2,428,291 reactions, which deduplicate to **1,432,318 distinct
structures** — a 10× collapse, and the same set `rdkit.mols` holds.

Screen-then-verify over the first 100,000 of them, 2048-bit pattern fingerprints:

| pattern | mode | screen | verify | retained | hits |
| --- | --- | ---: | ---: | ---: | ---: |
| `c1ccncc1` pyridine | SMILES | 2.6 ms | 0.05 s | 21.3% | 21,251 |
| `C(=O)O` carboxylic acid | SMILES | 8.2 ms | 0.06 s | 37.3% | 37,165 |
| `B(O)O` boronic acid | SMILES | 2.4 ms | 0.00 s | 0.7% | 740 |
| `c[F,Cl,Br,I]` aryl halide | SMARTS | 2.5 ms | 0.15 s | 99.8% | 34,029 |

Scaled to all 1,432,318 structures that is a **35–120 ms screen and a verify of up to
~2.1 s** — the worst case being the SMARTS query, whose screen retains essentially
everything because a fingerprint built from a query molecule discriminates poorly.
Similarity is cheaper still: a full Tanimoto scan against 2048-bit Morgan fingerprints
over the whole corpus takes **0.76 s**, and needs no verification pass because the score
*is* the answer.

The GiST indexes in `rdkit_mappers.py` are the right engineering at PubChem scale. At
1.4M structures they are optimizing a scan that already completes in the time it takes
to render a page.

### 4. The structure sidecar costs ~319 MB and about five minutes to build

Fingerprints are high-entropy, so the compression question is real. Measured on 50,000
structures written to Parquet with the same zstd codec the sources use:

| column | compressed, projected to 1,432,318 |
| --- | ---: |
| `pattern_fp` (2048-bit) | 209 MB |
| `morgan_fp` (2048-bit) | 85 MB |
| `smiles` | 24 MB |
| **total** | **319 MB** |

zstd gets fingerprints to 0.44 of raw, so the naive 733 MB estimate is wrong by more than
2×. That puts the structure sidecar at roughly the size of the reaction views themselves
(334 MB), for the capability that currently requires a Postgres instance with a
compiled extension.

Build cost, projected from the same sample: ~1.0 min to parse, ~2.6 min for pattern
fingerprints, ~0.4 min for Morgan — call it **five minutes**, alongside the 9.7 minutes
the reaction views already take.

Two properties make this artifact well-behaved. It is keyed by *distinct structure*, not
by reaction, so it is one corpus-wide file rather than a per-dataset column — and its
10× deduplication is why it is affordable at all. And it is pure tier 1 by the
[existing test](2026-07-25-derived-parquet-sidecars.md#1-two-tiers-split-by-contract--not-by-cost):
reproducible offline from the source protos with pinned open tooling, policy-free, and
wrong if it disagrees with its source.

### 5. DuckDB already handles the nesting; GraphQL solves a problem we do not have

Against the current sidecars, cold process:

| query | wall-clock |
| --- | ---: |
| `count(*)` over 2,428,291 rows | 0.03 s |
| `unnest(input_smiles)` + `GROUP BY`, 14.1M elements | 0.11 s |
| filtered aggregate on two scalar columns | 0.05 s |

The middle row is the important one: it is a nested-list query, written in ordinary SQL,
with no supporting machinery. Deeper nesting behaves the same way — `STRUCT` fields are
addressed with dot notation and pruned by the same projection pushdown.

GraphQL's purpose is letting a client specify a response shape so a *server* does not
over-fetch across a network. The sidecar design has no server and no network: the reader
opens the file and Parquet's column chunks make "select only what you need" the default,
not a feature to be built. Introducing GraphQL would mean operating a service, which is
precisely the cost this design exists to avoid — and it would not make the nesting more
accessible than `unnest` already does.

If a hosted query endpoint is wanted later, that is a deployment question about the
existing API, not a reason to change the storage format.

### 6. SQLite data packages lose on size and scans, win on point lookups

A versioned SQLite package is the serious alternative: one self-describing file with a
declared schema, real B-tree indexes, and `chemicalite` available as an RDKit extension.
It was built and measured rather than argued about — same corpus, same machine, a
`reaction` table plus a normalized `component` table (14.1M rows), indexed on component
SMILES, component `reaction_id`, and yield.

| | Parquet sidecars | SQLite package |
| --- | ---: | ---: |
| size | **333.9 MB** | 2,507.8 MB bare, **3,633.4 MB indexed** |
| build | — | 31.5 s load + 13.5 s index |
| `count(*)` | 0.03 s | **0.003 s** |
| component `GROUP BY`, top 5 | **0.11 s** | 9.73 s |
| filtered aggregate | **0.05 s** | 0.49 s |
| exact component → reactions | — | **0.023 s** |
| point lookup by `reaction_id` | — | **0.000 s** |

**10.9× the bytes and 10–88× slower on analytical scans**, against decisive wins on
indexed point access. Two structural reasons, not tuning artifacts:

- **Normalization repeats the key.** Parquet keeps components in a `LIST` inside the
  reaction row, so `reaction_id` is stored once. SQLite needs a `component` table, so a
  36-character ID is repeated across 14.1M rows — roughly 500 MB of nothing but foreign
  keys. An integer surrogate key would recover most of that; in fairness, a tuned schema
  probably lands near 2 GB rather than 3.6, which is still ~6× Parquet.
- **SQLite has no compression and no column pruning.** Parquet applies zstd per column
  chunk and reads only the chunks a query projects. A row store reads whole rows, which
  is why the aggregate touching two columns is 10× slower.

The honest read is that these are different tools rather than a better and a worse one.
SQLite is a *transactional row store with indexes*; Parquet is a *compressed columnar
scan format*. Analysis — the mode finding 7 identifies as unserved — is scan-shaped, and
that is what decides it here. If the dominant workload were "look up this reaction by
ID," SQLite would win outright.

`chemicalite` deserves a note because it is the strongest argument for SQLite: it brings
a `mol` type and substructure search via a virtual-table index, closing exactly the gap
the cartridge leaves. But finding 3 already closed that gap without it, and `chemicalite`
is a compiled extension the consumer must install — reintroducing the "needs a compiled
extension" dependency that finding 3 removes. Precomputed fingerprints plus numpy need
nothing but the RDKit wheel the consumer already has.

Two further points make this less of a fork than it looks. DuckDB can `ATTACH` a SQLite
file, so publishing one later is additive rather than a migration. And Hugging Face's
Data Studio previews Parquet, not SQLite — the sidecar entry's D5 (derived columns become
the Data Studio default) quietly depends on the format choice.

### 7. The two access modes are complementary, and the mediated one is already capped

`nl_query.py` is a genuine agent interface and it predates this discussion: it translates
free text into a forced `build_query` tool call, resolves compound names through
`ord_schema.resolvers` rather than model recall, and never writes SQL. For "find me
reactions that make ibuprofen with yield over 70%," it works today and a sidecar cannot
beat it on latency.

But it inherits the seven-predicate ceiling by construction, and `search.py` sets
`MAX_RESULTS = 1000`. Every result set is truncated at a thousand rows. An agent that
wants to compute an aggregate, fit a model, or assemble a training set cannot get the
data out through this path at any page size — the cap is on the query, not the page.

That is the clean division of labour. Lookup and search stay mediated, where the API's
grounding and caching earn their keep. Analysis goes direct, where a 334 MB file and
DuckDB beat any API that has to serialize rows over HTTP. Neither replaces the other,
and the direct path is the one that does not exist yet.

### 8. Full fidelity already exists; the sidecars should not chase it

`ord_schema/parquet.py` writes exactly two columns: `reaction_id` (string, non-null) and
`reaction` (serialized wire-format bytes, non-null). The complete proto is *already*
published on Hugging Face, per reaction, addressable by row group.

So "full fidelity in the sidecar" is not a capability gap — anything a sidecar could
carry is recoverable from `reaction` with one `FromString`. What the sidecar adds is
*queryability without deserialization*. That reframes the expansion question: the target
is not completeness, it is covering the fields agents filter, group, and join on, with
`reaction_id` as the escape hatch back to the full proto for everything else.

Concretely, that argues for a nested-but-curated expansion — inputs with roles and
amounts, the `ReactionConditions` block the current API leaves indexed and unreachable,
outcomes with their measurements as `LIST<STRUCT>` — and against a mechanical projection
of all 71 message types.

### 9. Source yields include values that no clamp would survive, and the view amplifies them

Found while sanity-checking a DuckDB aggregate that returned a mean "percentage" of
1.85×10¹⁵. Across the tier-1 views:

| | |
| --- | ---: |
| rows with a yield | 1,093,772 |
| outside [0, 100] | **68,882** (6.3%) |
| maximum | 9.02×10¹⁹ |

These are in the source protos, in USPTO — verified by deserializing
`ord-50b993b6ebfb4b48b92fb0b8d87e3751` and reading `measurement.percentage.value`
directly. The view is projecting them faithfully.

The view does make it worse, though. `_outcome_values` takes the **largest** YIELD
measurement on the first outcome, and that reaction carries both `90.5` and `9.02×10¹⁹`
— so the published column gets the garbage one. "Largest" is itself a policy choice, of
exactly the kind
[finding 1 of the sidecar entry](2026-07-25-derived-parquet-sidecars.md#1-two-tiers-split-by-contract--not-by-cost)
says does not belong in a view, and it is the choice most exposed to bad data. Worth
settling before #914 merges; a validation warning on out-of-range percentages is probably
the better place to address the underlying data.

### 10. Full rebuilds should pull sources from Hugging Face, not GitHub LFS

The corpus is 1.26 GB. GitHub's free LFS allowance is 1 GiB/month of bandwidth and a
data pack is 50 GiB — so a full pull per merge would burn the monthly allowance in about
forty rebuilds. That is not an immediate cliff, but it is waste with no upside, because
Hugging Face already hosts byte-identical copies of the same files and
`download_from_huggingface.py` already ships `DEFAULT_ALLOW_PATTERNS = ["data/**"]`.

[Finding 4 of the sidecar entry](2026-07-25-derived-parquet-sidecars.md#4-incrementality-is-an-io-optimization-not-a-compute-one)
established that incrementality is about bandwidth rather than CPU. This refines where
the bandwidth comes from: routine merges pull only the objects the commit changed, from
LFS; a version bump that invalidates everything pulls the *unchanged* datasets from HF,
where egress is free. Making the full rebuild `workflow_dispatch`-only is worth doing for
blast-radius reasons anyway, but it should not be the mechanism protecting the quota.

## Conclusions / next steps

- **D1 — Do not reproduce the ORM in Parquet.** Its 71 tables answer a Postgres
  constraint that Parquet does not have, and normalized joins are the wrong surface for
  the consumer this is being built for. Target the seven-predicate query surface, not the
  schema.
- **D2 — Do not build GraphQL.** DuckDB queries nested Parquet directly and projection
  pushdown already provides shape selection. GraphQL would add a server to a design whose
  central property is not having one.
- **D2b — Stay on Parquet rather than versioned SQLite packages.** Measured, SQLite is
  10.9× the bytes and 10–88× slower on the analytical scans that define the unserved
  mode, because normalization repeats the join key and a row store cannot prune columns.
  It wins on indexed point lookups, which is not the workload in question. Revisit if
  telemetry shows point access dominating; DuckDB can `ATTACH` SQLite, so adding one
  later is additive rather than a migration.
- **D3 — Add a structure sidecar** keyed by distinct component SMILES, carrying pattern
  and Morgan fingerprints. ~319 MB, ~5 minutes to build, and it is what converts
  SUBSTRUCTURE / SIMILAR / SMARTS from "needs Postgres with a compiled extension" into
  "needs a file." Tier 1 by the existing test.
- **D4 — Expand the reaction sidecar nested-but-curated**, not exhaustively. Inputs with
  roles and amounts, `ReactionConditions`, outcomes with measurements as `LIST<STRUCT>`.
  Full fidelity stays in the source `reaction` column, joinable on `reaction_id`.
- **D5 — Keep the mediated path and wrap it for agents.** `nl_query.py` already exists
  and is the right tool for lookup and search; MCP over it is small work. The sidecars
  serve analysis, which `MAX_RESULTS = 1000` makes impossible today.
- **D6 — The ORM becomes the website's backend, not the agent surface.** Whether it can
  eventually be retired depends on what `ord-interface` still needs from it, which this
  entry does not settle. Note that D3 removes the RDKit cartridge as a reason it must
  exist.
- **D7 — Full rebuilds source from Hugging Face.** Per-merge work continues to pull
  changed objects from LFS.

Open, and deliberately not decided here: how far D4 goes. The `ReactionConditions` block
alone is seven sub-messages, and each one added is a column set that must stay correct
forever. The size and build-time budget is comfortable — the question is contract
surface, which is the same question the near-empty `pressure_kilopascals` and
`conversion_percent` columns raise at eleven columns.

## References

- ORM shape and cartridge functionality: `ord-schema` `ord_schema/orm/mappers.py`
  (descriptor-driven table generation, single-table inheritance rationale),
  `ord_schema/orm/rdkit_mappers.py` (`RDKitMols`, GiST indexes on `mol`/`morgan_bfp`,
  `contains_substructure`, `is_similar`, `matches_smarts`), `ord_schema/orm/database.py`.
- Query surface: `ord-interface` `ord_interface/api/queries.py` (seven `ReactionQuery`
  subclasses; `ReactionComponentQuery.MatchMode`), `ord_interface/api/search.py`
  (`MAX_RESULTS = 1000`), `ord_interface/api/nl_query.py` and `nl_query_prompt.md`.
- Source serialization: `ord-schema` `ord_schema/parquet.py` (`_SCHEMA`: `reaction_id`
  plus wire-format `reaction` bytes).
- Tier-1 implementation and the corpus figures reused here: `ord_schema/views.py` and
  `ord_schema/scripts/derive_views.py` in
  [ord-schema#914](https://github.com/open-reaction-database/ord-schema/pull/914).
- Measurement scripts and a reproduction guide:
  [`assets/2026-07-30-agent-access-sidecars-or-orm/`](../assets/2026-07-30-agent-access-sidecars-or-orm/).
- Prior entry this builds on: [2026-07-25 derived parquet sidecars](2026-07-25-derived-parquet-sidecars.md).
- RDKit cartridge operators and their index backing:
  <https://www.rdkit.org/docs/Cartridge.html>.
- SQLite alternative: `chemicalite`, an RDKit extension providing a `mol` type and
  virtual-table substructure index (<https://github.com/rvianello/chemicalite>); DuckDB's
  `sqlite_scanner` for attaching SQLite files
  (<https://duckdb.org/docs/stable/core_extensions/sqlite>).
