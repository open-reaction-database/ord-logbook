# Normalized EAV versus normalized projection

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **Status:** final (decision: ship the projection; pure EAV is dominated)
- **Tags:** ord-data, ord-schema, parquet, duckdb, agents, eav, indexing, design

## Question

[The search-index entry](../2026-07-31-projection-search-index/README.md) left one decision open:
does a flat fact table *replace* the nested projection, or accompany it? Its D2 says the
question is load-bearing and the rest of that log is contingent on it.

This entry works the comparison dimension by dimension. Both candidates carry the same
normalizations settled in
[the agent-access entry](../2026-07-30-agent-access-sidecars-or-orm/README.md#2b-normalize-units-and-structural-identifiers--but-only-those):
united messages become canonical floats, structural identifiers collapse to one `smiles`,
every other identifier is kept. They differ only in shape.

- **Normalized projection** — one row per reaction, the proto's nesting preserved as
  `STRUCT` / `LIST` / `MAP`. 393 leaf columns, 1,240.7 MB, 20.3 min.
- **Normalized EAV** — one row per populated leaf: `reaction_id`, `path`, `entity_key`,
  and typed value columns. 196,539,598 rows, 1,111.4 MB, 120.8 min.

A third shape turns up partway through and turns out to matter more than either: the
**pivoted fact table**, one row per *entity* with that entity's fields as columns
(`role`, `component_index`, `smiles`, `identifier_type`, `identifier_value`). It is what
[the previous entry](../2026-07-31-projection-search-index/README.md) actually measured, and it is
not a pure EAV.

## Summary

**Ship the normalized projection. A total EAV is dominated.** It is 10.4% smaller and
costs 6× the build time (120.8 minutes against 20.3) while being *slower* on the queries
that matter, because any predicate spanning two fields of one entity needs a self-join
that the nested form gets structurally.

The design space turned out not to be binary, which is what the framing missed. The fast
flat artifact measured in [the previous entry](../2026-07-31-projection-search-index/README.md) is
not a pure EAV — it *pivots* an entity's fields onto one row, which is why it answers in
0.068 s where the total EAV needs 1.10 s for the same question. A pivoted table is
per-entity-type by construction, so it is an index over specific paths, not a universal
replacement. That is precisely the relationship the ORM's `derived.*` tables have to
`ord.*`, arrived at independently.

The flat shapes are simpler to query, portable across tools where the projection is not,
and self-describing through `SELECT DISTINCT path`. The projection has typed columns, a
schema that is its own contract, and co-membership by construction rather than by join
key.

The flat shapes still win several dimensions outright — single-leaf selection, schema discovery,
interop, schema evolution — and those wins are real and worth carrying into how the
projection is documented and indexed. But they do not add up to a replacement.

One finding cuts the other way and should temper the verdict: **the projection's headline
advantage does not survive leaving DuckDB.** Deep scalar access is
milliseconds because Parquet prunes to struct leaves — but `pandas.read_parquet` cannot
select a nested leaf by dotted path at all, so a pandas consumer reads the entire
`conditions` tree and traverses dicts per row. The columnar-pruning argument is
DuckDB- and pyarrow-specific. EAV behaves identically everywhere.

## Method

Measured against `ord-data` `main` at `e017725` (2,428,291 reactions, 1,256.5 MB of
source parquet). DuckDB 1.5.5, pandas 2.x, polars 1.x, single laptop process, cold.
Sizes are decimal.

Both artifacts are built directly from the source protos, not from each other — see
[finding 4 of the search-index entry](../2026-07-31-projection-search-index/README.md#4-the-two-artifacts-are-peers-not-a-chain).
Scripts are in
[`ASSETS.md`](ASSETS.md).

Two caveats on scope. The selection timings compare the projection against the
*component* fact table from the previous entry (17,021,402 rows, 186.2 MB), which covers
identifiers only; the total EAV is a superset and will be slower per query than that
slice. And the wide-analysis timings compare the tier-1 view against a reaction-scalar
fact table (2,764,347 rows, 54.1 MB) holding the same five columns — a like-for-like
comparison of shape, not of coverage.

## Findings

### 1. Selection: the pivoted fact table by 13×, the total EAV by 2×

| query | projection | total EAV | pivoted facts |
| --- | ---: | ---: | ---: |
| input `smiles = 'C1CCOC1'` | 0.78 s | 0.395 s | **0.052 s** |
| output `smiles = 'C1CCOC1'` | 0.74 s | 0.358 s | **0.031 s** |
| input named "THF" | 0.90 s | 1.104 s | **0.068 s** |

All three are interactive. The projection's 0.9 s is not a problem in isolation — it
becomes one in a UI issuing several predicates per page render, and is no problem at all
for an agent running an analysis. Note the total EAV loses the third row; finding 10
explains why, and it is the result the entry turns on.

### 2. Wide analysis: the flat shape again, against expectation

Entity-attribute-value shapes are supposed to lose here, paying a self-join per attribute
where a columnar layout pays one more column read. Measured on the same five reaction
scalars:

| query | columnar | facts | answer |
| --- | ---: | ---: | ---: |
| 2 attributes | 0.044 s | **0.015 s** | 48,654 |
| 3 attributes (2 self-joins) | 0.052 s | **0.030 s** | 18,334 |
| yield bucketed by temperature | 0.045 s | **0.023 s** | 44 buckets |

The reason is sparsity. `conversion_percent` is populated on 0.2% of rows and
`pressure_kilopascals` on 0.3%; the columnar form scans 2,428,291 rows either way, while
the fact table holds 7,026 pressure rows and touches only those. Classic EAV advice
assumes dense attributes. ORD is not dense, and the [coverage
table](../2026-07-25-derived-parquet-sidecars/README.md#the-shipped-tier-1-columns-and-how-much-of-the-corpus-fills-them)
quantifies exactly how sparse.

### 3. Ergonomics: EAV, and the projection has a trap

```sql
-- EAV: what a consumer writes first, and it is also the fast form
WHERE role = 'INPUT' AND identifier_type = 'NAME' AND identifier_value = 'THF'

-- projection: what a consumer writes first, and it does not finish in four minutes
FROM p, UNNEST(map_values(inputs)) t(i), UNNEST(i.components) u(c), UNNEST(c.identifiers) v(x)
WHERE x.type = 'NAME' AND x.value = 'THF'

-- projection: what it has to be rewritten as, for 0.90 s
WHERE len(list_filter(
        flatten(list_transform(map_values(inputs), i -> i.components)),
        c -> len(list_filter(c.identifiers, x -> x.type='NAME' AND x.value='THF')) > 0)) > 0
```

The `UNNEST` form is idiomatic, is what every tutorial teaches, and is 27–200× slower.
This is the sharpest argument against the projection as a *primary* surface: its failure
mode is silent and looks like the format being unusable rather than the query being
wrong.

### 4. Interop: EAV, decisively — and this undercuts the projection's core claim

The projection's central performance argument is that Parquet stores each struct leaf as
its own column chunk, so depth is free. That is true of the *file*. It is not true of
every reader:

| reader | nested leaf access |
| --- | --- |
| DuckDB | `conditions.temperature.setpoint.value_kelvin`, prunes to the leaf, 0.006 s |
| pyarrow | leaf selection supported |
| polars | struct stays typed; `.struct.field()` reaches in |
| **pandas** | **cannot select a leaf by dotted path** (`ArrowInvalid`) — reads the whole `conditions` struct as `object` dtype, one `dict` per row |

A pandas user asking for one temperature column pays for the entire conditions tree plus
per-row dict traversal. Given how much analysis happens in pandas, the projection's
advantage is narrower than its headline suggests. The flat table reads identically in all
four.

### 5. Schema discovery: EAV, unexpectedly

`SELECT DISTINCT path` returns **81 paths in 0.013 s** on USPTO. That is better than it
sounds for two reasons: it is queryable rather than requiring schema introspection, and
it reports what is actually *populated* rather than what is declarable. The projection's
393-leaf schema is self-documenting but includes every leaf the proto permits, most of
which no dataset fills.

The counter is that EAV has no schema to enforce the path convention. A typo in a `path`
string produces zero rows rather than an error, where a typo in a column name is caught
by the query planner.

### 6. Overhead: modest, and not where expected

Per-column bytes in the EAV (USPTO, 40k reactions):

| column | share |
| --- | ---: |
| `value_text` | 77.1% |
| `entity_key` | 13.0% |
| `path` | 3.5% |
| `value_double` | 3.1% |
| `reaction_id` | 2.8% |
| `value_bool` | 0.5% |

Bookkeeping is **19.3%**; the rest is payload. `entity_key` carries positional indices and
is therefore high-cardinality, which is why it dominates the overhead — but zstd handles
the repeated prefixes well enough that it costs a tenth of the file rather than a third.
Dropping full positional fidelity for a compact integer index would recover most of that
13% at the cost of ordering.

### 7. Co-membership and types: the projection

Two dimensions where the projection is simply better, and both are correctness rather
than performance.

**Co-membership is structural.** "A component that is both named THF *and* over 5 mL"
runs natively in 0.80 s. In EAV it needs `entity_key` in the join, and the failure mode is
silent: drop the key and the query answers "a reaction containing an X and a Y" — a
different, larger set — without any error. Measured, the correct join costs 0.070 s and
the two questions return 0 and 5,021 respectively, so the distinction is real, not
theoretical.

**Types are declared.** The projection has `temperature_kelvin DOUBLE`. EAV splits values
across `value_text` / `value_double` / `value_bool`, and reading the wrong one returns
nulls rather than an error. That is a documentation-and-convention burden the projection
does not have.

### 8. Schema evolution: EAV

A new proto field becomes new rows in EAV and a new column in the projection. Consumers of
the EAV are unaffected; consumers of the projection see a schema change, and anything
pinned to a column list has to be revisited. Given that the projection is generated from
the descriptors precisely so that schema changes propagate automatically, EAV propagates
them more gently.

### 9. Size and build time: EAV is smaller and much more expensive to build

Full corpus, normalized both ways:

| | rows | size | vs source | build |
| --- | ---: | ---: | ---: | ---: |
| source parquet | 2,428,291 | 1,256.5 MB | — | — |
| normalized projection | 2,428,291 | 1,240.7 MB | 0.99× | **20.3 min** |
| normalized total EAV | 196,539,598 | **1,111.4 MB** | **0.88×** | 120.8 min |

The EAV is **10.4% smaller** — 80.9 facts per reaction at 457.7 bytes per reaction — and
takes **6× as long to build**. Both figures come from unoptimized pure-Python descriptor
walks, so the ratio is more trustworthy than either absolute; but the ratio is the
problem. Two hours is outside what a routine CI job should carry, where twenty minutes
is not.

### 10. Query speed splits on whether co-membership is needed

This is the finding that decides the entry, and it separates the *total* EAV from the
partially-pivoted fact table that the previous entry measured.

| query | projection | total EAV | component facts |
| --- | ---: | ---: | ---: |
| input `smiles = 'C1CCOC1'` | 0.78 s | **0.395 s** | 0.052 s |
| output `smiles = 'C1CCOC1'` | 0.74 s | **0.358 s** | 0.031 s |
| input **named** "THF" | **0.90 s** | 1.104 s | 0.068 s |

A predicate on a single leaf is a filtered scan of one dense path slice, and the EAV wins
it outright. A predicate spanning two fields of the *same entity* — matching
`identifiers.type = 'NAME'` against `identifiers.value = 'THF'` — needs a self-join,
because `entity_key` is per-leaf: `identifiers[0].type` and `identifiers[0].value` carry
*different* keys. The join therefore has to derive the parent key by stripping the last
path component with a regex, and the EAV loses.

The 0.068 s column is not pure EAV and should not be read as one. The component fact
table pivots `identifier_type` and `identifier_value` onto the same row, so the join
never happens. That is why it is fifteen times faster than the total EAV at the same
question — and also why it cannot generalize, since a pivoted table is specific to one
entity type. This is exactly the shape of the ORM's `derived.*` tables, which are
per-entity rather than universal.

### 11. The silent-failure mode is not theoretical; it fired during this entry

The first version of the "input named THF" query above joined on `entity_key` equality
rather than the derived parent key. It returned **0**, which is a plausible-looking
answer, not an error. The projection and the component fact table both say 145,285.

That is the concrete cost of finding 7's abstraction. A shape whose wrong query returns a
credible number is materially worse to hand to an agent than one whose wrong query is
slow, because slowness is self-announcing and a wrong count is not. Once corrected, all
four artifacts — tier-1 view, projection, component facts, total EAV — agree at 145,285.

## Conclusions / next steps

- **D1 — Ship the normalized nested projection as the capability artifact.** 1,240.7 MB,
  20.3 min, sub-second on every query tried. It answers arbitrary questions over the full
  model, and co-membership is structural rather than reconstructed.
- **D2 — Do not ship a total EAV.** It is dominated: 10.4% smaller for **6× the build
  time**, and slower than the projection on any predicate spanning two fields of one
  entity, which includes the most common question in the corpus. Its wins on single-leaf
  selection and interop are real but do not add up to a replacement.
- **D3 — Pivoted per-entity fact tables stay available as indexes.** The component table
  from [the search-index entry](../2026-07-31-projection-search-index/README.md) is 13× faster than
  the projection at 186.2 MB and 8.7 min. It is per-entity-type by construction, so it
  indexes specific paths rather than replacing the projection — the same relationship
  `derived.*` has to `ord.*` in the ORM. Publish when a consumer needs it, not before.
- **D4 — Document the `UNNEST` trap wherever the nested form ships.** Idiomatic and
  27–200× slower. A consumer who writes it concludes the artifact is unusable.
- **D5 — Document the pandas limitation too.** `read_parquet` cannot select a nested leaf
  by dotted path, so the pruning that makes deep access free in DuckDB does not transfer.
  Consumers doing pandas analysis should be pointed at the tier-1 view or a pivoted index
  rather than the projection.
- **D6 — Keep the tier-1 view as the flat starter table.** Its job is neither capability
  nor speed but *approachability*: a column set a consumer can read at a glance, and the
  only one of the three that previews usefully in Hugging Face Data Studio. That reframes
  its near-empty columns — `pressure_kilopascals` (3 of 53 datasets) and
  `conversion_percent` (6 of 53) — as cost without benefit, since both are reachable in
  the projection regardless.

The methodological note worth keeping: every intuition this thread started with was
wrong, and each was corrected only by building the thing. Nested queries were assumed
slow (they are sub-second), EAV was assumed bad at wide analysis (it is faster), the
artifacts were assumed to form a chain (they are peers), and a total EAV was assumed able
to stand alone (it is dominated). The one prediction that held was that the fast flat
table would beat the projection on selection — and even that turned out to be measuring a
pivoted table rather than the EAV being argued about.

## References

- Prior entries: [2026-07-31 does the projection need a search index?](../2026-07-31-projection-search-index/README.md)
  (the open decision this addresses), [2026-07-30 unlocking agents](../2026-07-30-agent-access-sidecars-or-orm/README.md)
  (the projection and its normalizations), [2026-07-25 derived parquet sidecars](../2026-07-25-derived-parquet-sidecars/README.md)
  (tier-1 contract and the sparsity that finding 2 turns on).
- Scripts: [`ASSETS.md`](ASSETS.md),
  and the projection and fact-table builders in the two prior entries' assets.
- DuckDB list lambdas: <https://duckdb.org/docs/stable/sql/functions/lambda>.
