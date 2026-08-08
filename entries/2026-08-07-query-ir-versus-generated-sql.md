# Should a natural-language query compile to SQL, or to an IR?

- **Date:** 2026-08-07
- **Author:** Steven Kearnes
- **Status:** draft (proposal; prototype measured, not built)
- **Tags:** ord-schema, agents, nl-query, duckdb, projection, design

## Question

[The 2026-07-31 entry](2026-07-31-nl-query-over-the-projection.md) settled that a
natural-language query compiles to **generated DuckDB SQL** with compounds pulled out as
bound placeholders, on the grounds that no finite enumeration reaches 389 columns. The
first half of that design shipped as
[ord-schema#948](https://github.com/open-reaction-database/ord-schema/pull/948): a
generated schema description for the prompt, and a validator that plans generated SQL
against an empty table.

Reviewing it raised the question the earlier entry treated as closed: should the model
emit SQL at all, or a structured query the library compiles?

## Summary

**An IR, compiled to SQL. The earlier entry's argument does not reach one, and the
property it gives up is the one that matters most.**

The argument against structure was that `NLQuery` is "an enumeration, not a query
language" — one field per ORM predicate, so every new question shape costs a field. That
is true of `NLQuery` and false of a query IR, because the two enumerate different things.
`NLQuery` enumerated **question shapes** (`min_yield`, `max_yield`, `reaction_smarts`).
An IR enumerates **operators** (`eq`, `lt`, `contains`, `exists`, `forall`) and takes the
column path as a *parameter*. Columns become data rather than grammar, so 389 of them
cost nothing. The earlier entry rejected a specific bad structured design and generalized
the verdict to structure itself.

Meanwhile, accepting SQL makes query cost **unguardable rather than merely unguarded**.
`sql.validate` refuses `UNNEST` in a `FROM` clause — the one hazard the earlier entry
identified — and accepts a self-join over 2.4M reactions, a cross join against `range`, a
recursive CTE counting to a billion, and a predicate-free `SELECT *`. Entries can be
added to that blacklist but it cannot be finished: the set of expensive programs
expressible in SQL is not enumerable. Under an IR the question does not arise, because
**every program the grammar can express costs one pass over the corpus plus a sort.**
There is no join construct, no recursion, and no cross product to write.

The `UNNEST` hazard turns out to be a symptom of the same thing rather than a separate
risk. A model reaches for the textbook idiom because the grammar permits it; a compiler
emits list lambdas by construction, and the 27–200× cliff stops existing rather than
being policed.

A prototype compiler agrees with hand-written SQL on every query tried, at the same
speed, and refuses at compile time a class of ambiguity that SQL accepts silently.

## Method

Prototype at
[`assets/2026-08-07-query-ir-versus-generated-sql/ir.py`](../assets/2026-08-07-query-ir-versus-generated-sql/ir.py)
— roughly 100 lines covering paths, comparisons, boolean combinators, `exists`/`forall`,
and a `group_by` aggregate. Paths resolve against `projection.SCHEMA`, so every column
reference and every quantifier position is checked against the real 442-leaf shape
before any SQL exists -- 389 when the earlier entry counted, before a precision column
per united field landed in #947.

Measured against the projection of `ord_dataset-488402f6` (40,000 USPTO reactions),
DuckDB 1.5.5, single laptop process. Bypass testing ran against `ord_schema.agent.sql`
as merged on #948.

## Findings

### 1. Every guard on generated SQL is a blacklist, and the blacklist has one entry

All of these pass `sql.validate` today:

| query | scale |
| --- | --- |
| `FROM reactions a, reactions b WHERE a.smiles = b.smiles` | 5.9 × 10¹² rows |
| triple self-join | 10¹⁹ |
| `FROM reactions, range(1000000000)` | 10⁹ per row |
| `generate_series(1, 1000000000)` | 10⁹, touches no table |
| `WITH RECURSIVE t(n) AS (… n < 1000000000) SELECT count(*) FROM t` | unbounded, no table |
| correlated `(SELECT count(*) FROM reactions)` per row | quadratic |
| `SELECT * FROM reactions` | no predicate at all |

Each is fixable individually and the list does not terminate. This is a property of
accepting SQL, not of this validator.

### 2. The IR's cost bound is structural

The grammar has one relation, no join, no recursion, and no set-returning function. A
predicate is a filter over list children; an aggregate is a hash over rows; an order is a
sort. So the worst program the model can emit is **one pass over the corpus plus a
sort** — which the [2026-07-31 index entry](2026-07-31-projection-search-index.md)
measured at 0.90 s for the heaviest nested predicate over the full corpus.

That is the whole argument. Not "expensive queries are harder to write" — they are
*unwritable*.

### 3. The IR refuses an ambiguity SQL accepts silently

A path crossing a repeated level with no quantifier is rejected at compile time:

```text
inputs.components.smiles crosses a repeated level; wrap it in exists/forall so the
quantifier is stated rather than assumed
```

In SQL the same intent is spelled `UNNEST`, which silently means "any" *and* changes the
row count — the trap the index entry documented when a `DISTINCT` was needed to make two
spellings agree. The IR has no way to leave the quantifier unstated.

It also keeps the co-membership distinction the fact-table design could not express:
`exists(component, A and B)` is "one component that is both", while
`exists(component, A) and exists(component, B)` is "a reaction containing each". Both are
writable, and they are different nodes rather than a subtlety of join keys.

### 4. The prototype agrees with hand-written SQL, at the same speed

| query | IR | hand-written | agree |
| --- | ---: | ---: | :---: |
| exists input component `smiles = C1CCOC1` | 6,008 / 0.069 s | 6,008 / 0.057 s | yes |
| same component is THF **and** a REACTANT | 6,008 / 0.056 s | 6,008 / 0.057 s | yes |
| forall input components are REACTANT | 40,000 / 0.061 s | 40,000 / 0.058 s | yes |
| exists product smiles contains `F` | 9,641 / 0.111 s | 9,641 / 0.108 s | yes |

The compiler emits the fast idiom because it cannot emit anything else:

```sql
SELECT reaction_id FROM reactions
WHERE len(list_filter(
        flatten(list_transform(map_values(inputs), x -> x.components)),
        e0 -> (len(list_filter(e0.identifiers,
                               e1 -> (e1.type = 'NAME' AND e1.value = 'THF'))) > 0
               AND e0.amount.volume_liters > 0.0))) > 0
```

One bug found while prototyping is worth recording, because it is the failure mode a
compiler has and a prompt does not: a nested quantifier initially resolved its inner path
against the *row* rather than the bound element, so `identifiers` silently bound to the
reaction's own column and the query returned a wrong answer rather than an error. A
compiler concentrates that class of mistake into code that can be unit-tested, instead of
distributing it across every query a model writes.

### 5. What the IR gives up

Arbitrary expressions (`yield / temperature`), window functions, and joins against
anything else. `group_by` plus an aggregate covers "which catalyst gives the highest
average yield", which is a fair natural-language question and the main reason not to ship
a pure predicate language — but the general analytical surface is not reachable and
should not be.

That is the line [the agent-access entry](2026-07-30-agent-access-sidecars-or-orm.md)
already drew: lookup and search stay mediated, analysis goes direct. An analyst wanting a
window function opens the Parquet file in DuckDB, where the user is a human who is not the
injection risk and whose slow query harms only their own session.

## The grammar

```text
Query      = { where?: Predicate, aggregate?: Aggregate,
               order_by?: [Order], limit?: int }

Predicate  = { op: "and" | "or", clauses: [Predicate] }
           | { op: "not", clause: Predicate }
           | { op: "exists" | "forall", path: Path, where: Predicate }
           | { op: "eq"|"ne"|"lt"|"le"|"gt"|"ge", path: Path, value: Value }
           | { op: "contains"|"starts_with"|"ends_with", path: Path, value: Value }
           | { op: "is_null" | "not_null", path: Path }

Value      = { literal: <scalar> } | { compound: <name> }

Aggregate  = { group_by: [Path],
               measures: [{ fn: "count"|"count_distinct"|"sum"|"avg"|"min"|"max",
                            path?: Path, as: string }] }

Order      = { key: string, desc?: bool }
```

Rules the compiler enforces from `projection.SCHEMA`, all of them before any SQL exists:

- A `Path` is a dotted column path. Inside `exists`/`forall` it is **relative to the
  bound element**.
- A comparison path must terminate at a scalar and must **not** cross a repeated level.
- An `exists`/`forall` path must terminate **at** a repeated level.
- Comparison operators must suit the leaf type; `contains` is string-only.
- `group_by` paths must be scalar and must not cross a repeated level, so grouping
  cardinality is bounded by the column rather than by an explosion.
- A `{compound: name}` value is resolved through `ord_schema.resolvers` and bound as a
  parameter, never interpolated — the property from the earlier entry that survives
  unchanged.

## Alternatives considered

Reviewing the prototype raised the fair question of whether any of this already exists.

**Ibis compiles the hard part, and compiles it well.** Given the same query it emits
`ARRAY_LENGTH(LIST_FILTER(FLATTEN(LIST_APPLY(MAP_VALUES(inputs), ...))))` — the same
shape as the prototype, no `UNNEST` — returns the same 6,008 rows, and runs in 0.056 s
against the prototype's 0.059 s on a warm connection. It is 22 MB and its dependencies
(pyarrow, duckdb, sqlglot) largely overlap what `ord-schema` already carries.

What it does not supply is the IR. Ibis expressions are built by Python method calls
taking **lambdas**, and a model cannot emit a lambda — evaluating model-supplied Python
is exactly the surface this design removes. The JSON grammar stays ours either way, and
so does the restriction: Ibis has `.join()`, so the cost bound comes from refusing to
expose operations rather than from anything Ibis provides. Adopting it would replace
about 100 lines of expression building with about 80 lines of IR-to-Ibis mapping, and
path resolution would still have to know a map from a list. Worth revisiting the moment
a second dialect is needed — hand-writing a second generator would not be.

**The document-query translators do not fit.** The published packages in this space
translate between *flat* relational and document models for migration. None compiles a
nested-document predicate into list lambdas over
`MAP<VARCHAR, STRUCT<components: LIST<STRUCT<...>>>>`, which is the whole problem.

## Conclusions / next steps

- **D1 — The model emits the IR, not SQL.** The library compiles and executes it.
  Affordability, injection, and the `UNNEST` idiom all stop being things a prompt has to
  get right.
- **D2 — Revise [2026-07-31](2026-07-31-nl-query-over-the-projection.md).** Its finding
  that the schema fits in a prompt still holds and is what makes either design possible.
  Its conclusion that structure cannot scale to 389 columns is wrong as stated: it
  applies to per-predicate fields, not to a parameterized grammar.
- **D3 — Keep `schema.describe()` unchanged.** A compiler still has to tell the model
  which columns exist, and the generated-from-`build_schema()` property is what keeps the
  prompt from drifting. It carries over from #948 untouched.
- **D4 — Demote `sql.validate` to a backstop.** It stops being the guard and becomes a
  check on the compiler's own output, where a `SELECT`-only, no-filesystem, plans-cleanly
  assertion is cheap insurance against a compiler bug. Its warning that it does not bound
  cost stays true and stays necessary.
- **D5 — Execution still needs a sandbox.** Deferred from #948 and unchanged by this:
  `enable_external_access=false` cannot be used with a lazy Parquet view, so running
  against the real corpus needs `allowed_directories` or a subprocess. An IR removes the
  reasons to *fear* the query, not the reasons to contain the process.

Open: whether `forall` earns its place (it is easy to compile and easy to misread — "all
products are alcohols" is true of a reaction with no products), and whether `order_by`
should accept only aggregate output names rather than arbitrary paths.

## References

- Prior entries: [2026-07-31 what should a natural-language query compile
  to?](2026-07-31-nl-query-over-the-projection.md) (the conclusion this revises),
  [2026-07-31 does the projection need a search index?](2026-07-31-projection-search-index.md)
  (the `UNNEST` measurements and the co-membership argument),
  [2026-07-30 unlocking agents](2026-07-30-agent-access-sidecars-or-orm.md) (the
  mediated/direct split).
- ord-schema [#948](https://github.com/open-reaction-database/ord-schema/pull/948) — the
  schema description and SQL validator this builds on.
- DuckDB list lambdas: <https://duckdb.org/docs/stable/sql/functions/lambda>.
