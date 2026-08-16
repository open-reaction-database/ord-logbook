# What should a natural-language query compile to?

- **Date:** 2026-07-31
- **Author:** Steven Kearnes
- **Status:** draft (design settled, not yet built)
- **Tags:** ord-schema, agents, nl-query, duckdb, projection, design

## Question

[The projection](../2026-07-31-projection-search-index/README.md) exists to unlock a much larger
query surface than the search backend has today. That raises a question the existing
translation layer never had to answer: when a chemist asks a question in English, what
should the model actually emit?

The existing implementation answers "a fixed structured object." The question is whether
that answer survives contact with a 389-column schema, and if not, what replaces it.

## Summary

**It does not survive, and the replacement is generated SQL with the compounds pulled
out.** The model emits DuckDB SQL against the projection, plus a separate list of the
compounds it referenced by name; those are resolved deterministically and bound as
parameters.

The existing `NLQuery` is a pydantic model whose fields are `components`, `min_yield`,
`max_yield`, `min_conversion`, `max_conversion`, `reaction_smarts`,
`similarity_threshold`, `use_stereochemistry`, and `limit` — the current ORM backend's
predicate list, transcribed. It is not a query language; it is an enumeration. Every new
question shape costs a field, a prompt edit, and a backend change, and no finite
enumeration reaches 389 columns. Widening it is not a scaling strategy.

The pivotal realization is that emitting SQL does **not** require giving up the property
that made the old design trustworthy. The model never wrote SMILES — it passed through
the user's own words and a deterministic resolver grounded them. That property is
orthogonal to the output format, and it survives if compounds leave the SQL as named
placeholders.

## Method

Two things were checked before committing to the design.

**What in the existing module is reusable.** Read
[`ord_schema/agent/nl_query.py`](https://github.com/open-reaction-database/ord-schema/pull/919/files)
as it stood on the (now closed) move PR and classified each symbol as
surface-independent or tied to the current backend.

**Whether the schema fits in a prompt.** Rendered `projection.SCHEMA` as an indented
type tree and measured it. This is the load-bearing question for the whole approach: if
the schema does not fit, the model needs a column-search tool and a multi-turn loop
instead of a single forced call.

## Findings

### About a third of the existing module is reusable

| Surface-independent | Encodes the current backend |
|---|---|
| `NLQueryError` and its three subclasses | `NLQuery` — one field per ORM predicate |
| `Cache` protocol | `NLComponent` — `INPUT`/`OUTPUT`, four match modes |
| `get_client`, `model_name`, model constants | the `build_query` tool schema |
| name resolution with caching | the system prompt (42 lines) |
| loading the prompt from markdown | the eval cases (140 lines) |

Roughly 115 of 365 lines carry over. That ratio is why the move PR was closed rather
than merged: porting the rest would have started the new work from a template pulling
back toward the shape being replaced.

### The schema fits in a prompt with room to spare

Rendered as an indented type tree, the full projection schema is **12,056 characters
across 594 lines — on the order of 3,000 tokens**, from 11 top-level fields expanding to
389 leaves.

That is a comfortable system prompt. The entire query surface can be stated up front, so
translation stays a single forced tool call rather than a retrieval loop over column
metadata. It also means the description should be *generated* from `build_schema()`
rather than hand-written, so the prompt cannot drift from the data it describes.

### Units are already carried by the column names

The projection's unit normalization pays off a second time here. Leaves arrive as
`mass_grams`, `moles_moles`, `volume_liters`, `setpoint_kelvin` — so the model reads
units off the schema it was already given, and an entire category of unit-conversion
error leaves the prompt's job. Nothing has to explain that temperatures are kelvin.

### Three properties follow from placeholders

Compounds leaving the SQL as named placeholders — `... WHERE list_contains(inputs.smiles,
$thf)` with `thf → "THF"` declared alongside — buys three things at once:

1. **The model still never invents a structure.** It names compounds; `resolvers.py`
   grounds them via PubChem/CIR/OPSIN. Hallucinated SMILES remain impossible by
   construction, exactly as before.
2. **Binding, not interpolating.** A compound name cannot carry SQL into the query,
   because it never reaches the query as text.
3. **Validation is free and needs no data.** `build_schema()` yields the Arrow schema, so
   an empty DuckDB view with the real 389-column shape validates generated SQL by
   `EXPLAIN` — no corpus, no fixture. The validator and the prompt derive from the same
   call, so neither can drift from the Parquet.

### The known hazard is `UNNEST`

[Measured earlier](../2026-07-31-projection-search-index/README.md): `UNNEST` in a `FROM` clause
materializes exploded rows and runs **27–200× slower** than list lambdas for identical
answers. A model writing SQL over a nested schema will reach for it — it is the textbook
spelling.

This is the one place where the freedom of SQL genuinely costs something the fixed schema
never risked, since `NLQuery` could not express a bad plan. Mitigation is a prompt rule
plus, optionally, a validator check on the plan shape. Worth watching in evaluation
rather than assuming the prompt handles it.

## Conclusions / next steps

Build the replacement as a fresh package rather than a port:

- **Generic core** — error hierarchy, `Cache` protocol, client and model selection, name
  resolution with caching. Carried over from the closed PR.
- **Projection-targeting translation** — schema description and validator both generated
  from `build_schema()`, prompt rewritten around SQL and the `UNNEST` hazard, compounds
  emitted as placeholders.

Sequenced after [#918](https://github.com/open-reaction-database/ord-schema/pull/918),
which the translation needs for `build_schema()`.

ord-interface is deliberately untouched until then. Its current backend keeps working,
and when projection-backed search lands the old module is deleted in one move rather than
refactored twice.

Open questions for evaluation: whether prompt rules alone keep the model off `UNNEST`, and
whether a read-only guard belongs in the validator or in how the connection is opened.

## References

- [Agent access: sidecars or the ORM?](../2026-07-30-agent-access-sidecars-or-orm/README.md)
- [Does the projection need a search index?](../2026-07-31-projection-search-index/README.md)
- [EAV versus the projection](../2026-07-31-eav-versus-projection/README.md)
- ord-schema [#918](https://github.com/open-reaction-database/ord-schema/pull/918) — the
  projection
- ord-schema [#919](https://github.com/open-reaction-database/ord-schema/pull/919) —
  closed; the move this entry supersedes
- ord-interface [#216](https://github.com/open-reaction-database/ord-interface/pull/216) —
  closed alongside it
