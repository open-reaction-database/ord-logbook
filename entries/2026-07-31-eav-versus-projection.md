# Normalized EAV versus normalized projection

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **Status:** draft (size and build time pending; every other dimension measured)
- **Tags:** ord-data, ord-schema, parquet, duckdb, agents, eav, indexing, design

## Question

[The search-index entry](2026-07-31-projection-search-index.md) left one decision open:
does a flat fact table *replace* the nested projection, or accompany it? Its D2 says the
question is load-bearing and the rest of that log is contingent on it.

This entry works the comparison dimension by dimension. Both candidates carry the same
normalizations settled in
[the agent-access entry](2026-07-30-agent-access-sidecars-or-orm.md#2b-normalize-units-and-structural-identifiers--but-only-those):
united messages become canonical floats, structural identifiers collapse to one `smiles`,
every other identifier is kept. They differ only in shape.

- **Normalized projection** — one row per reaction, the proto's nesting preserved as
  `STRUCT` / `LIST` / `MAP`. 393 leaf columns, 1,240.7 MB, 20.3 min.
- **Normalized EAV** — one row per populated leaf: `reaction_id`, `path`, `entity_key`,
  and typed value columns. Size and build time pending.

## Summary

**EAV wins the dimensions that decide whether an agent succeeds; the projection wins the
dimensions that decide whether it succeeds *correctly*.** That is a real tension rather
than a walkover, and it is why this entry does not hand down a verdict before the size
measurement lands.

EAV is faster on selection (13×) *and* on multi-attribute analysis (2–3×), simpler to
query, portable across tools where the projection is not, and self-describing through
`SELECT DISTINCT path`. The projection has typed columns, a schema that is its own
contract, and co-membership by construction rather than by join key.

The single most consequential finding is one neither shape was chosen for: **the
projection's headline advantage does not survive leaving DuckDB.** Deep scalar access is
milliseconds because Parquet prunes to struct leaves — but `pandas.read_parquet` cannot
select a nested leaf by dotted path at all, so a pandas consumer reads the entire
`conditions` tree and traverses dicts per row. The columnar-pruning argument is
DuckDB- and pyarrow-specific. EAV behaves identically everywhere.

## Method

Measured against `ord-data` `main` at `e017725` (2,428,291 reactions, 1,256.5 MB of
source parquet). DuckDB 1.5.5, pandas 2.x, polars 1.x, single laptop process, cold.
Sizes are decimal.

Both artifacts are built directly from the source protos, not from each other — see
[finding 4 of the search-index entry](2026-07-31-projection-search-index.md#4-the-two-artifacts-are-peers-not-a-chain).
Scripts are in
[`assets/2026-07-31-eav-versus-projection/`](../assets/2026-07-31-eav-versus-projection/).

Two caveats on scope. The selection timings compare the projection against the
*component* fact table from the previous entry (17,021,402 rows, 186.2 MB), which covers
identifiers only; the total EAV is a superset and will be slower per query than that
slice. And the wide-analysis timings compare the tier-1 view against a reaction-scalar
fact table (2,764,347 rows, 54.1 MB) holding the same five columns — a like-for-like
comparison of shape, not of coverage.

## Findings

### 1. Selection: EAV by 13×

| query | projection | facts |
| --- | ---: | ---: |
| input named "THF" | 0.90 s | **0.068 s** |
| input `smiles = 'C1CCOC1'` | 0.78 s | **0.052 s** |
| output `smiles = 'C1CCOC1'` | 0.74 s | **0.031 s** |

Both are interactive. The projection's 0.9 s is not a problem in isolation — it becomes
one in a UI that issues several predicates per page render, and it is not a problem at
all for an agent running an analysis.

### 2. Wide analysis: EAV again, against expectation

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
table](2026-07-25-derived-parquet-sidecars.md#the-shipped-tier-1-columns-and-how-much-of-the-corpus-fills-them)
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

### 9. Size and build time: pending

The measurement in flight. The un-normalized total EAV cost 732.8 bytes per reaction on
USPTO against the raw projection's 809.8; normalization took 22.3% off USPTO in the
projection, so the open question is whether the same holds here. Against the normalized
projection's 1,240.7 MB and 20.3 minutes.

## Conclusions / next steps

Not yet settled — finding 9 decides it, and this section will be rewritten when it lands.
What is already clear:

- **If EAV lands at or below the projection's size**, ship EAV alone. Its wins are on the
  axes that determine whether a consumer gets an answer at all; the projection's wins are
  real but are addressable with documentation and a stamped path registry.
- **If EAV lands well above**, keep both as
  [the search-index entry](2026-07-31-projection-search-index.md) describes: projection as
  the typed authority, EAV as the selection index.
- **Either way, the `UNNEST` trap must be documented** wherever the nested form ships, and
  **an entity key must be carried** wherever the flat form ships. Those two are
  independent of the size result.
- **Either way, the tier-1 view survives** as the flat starter table. Eleven columns that
  a consumer can read at a glance is a different job from both candidates, and it is the
  only one of the three that previews usefully in Hugging Face Data Studio.

## References

- Prior entries: [2026-07-31 does the projection need a search index?](2026-07-31-projection-search-index.md)
  (the open decision this addresses), [2026-07-30 unlocking agents](2026-07-30-agent-access-sidecars-or-orm.md)
  (the projection and its normalizations), [2026-07-25 derived parquet sidecars](2026-07-25-derived-parquet-sidecars.md)
  (tier-1 contract and the sparsity that finding 2 turns on).
- Scripts: [`assets/2026-07-31-eav-versus-projection/`](../assets/2026-07-31-eav-versus-projection/),
  and the projection and fact-table builders in the two prior entries' assets.
- DuckDB list lambdas: <https://duckdb.org/docs/stable/sql/functions/lambda>.
