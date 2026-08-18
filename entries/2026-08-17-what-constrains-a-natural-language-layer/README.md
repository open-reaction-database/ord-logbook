# What constrains a natural-language layer over the search grammar

- **Date:** 2026-08-17
- **Author:** Steven Kearnes
- **Status:** final (the design that follows from it is [beside this entry](assets/nl-search-design.md))
- **Tags:** ord-schema, agents, search, natural-language, structured-outputs, anthropic, cost
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`ord_schema.search` gives a model a validated `Query` grammar to write against instead of
SQL. The layer that turns a chemist's sentence into one of those queries has never
shipped: it exists on the unmerged `nl-query-backend` branch, written against a flat IR
that predates the grammar, and the `/ask` deployment it served has since been moved out
from under it.

Rebuilding it raises one question that decides the whole design. Can the model be
*constrained* to emit a valid `Query` — structured outputs or a strict tool, where the
decoder itself refuses anything off-grammar — or does the layer have to accept whatever
comes back and check it afterwards? And with that settled: how good is a cheap model, and
what does a query cost?

## Summary

**Constrained decoding cannot carry this grammar.** Four separate walls, each hit
directly against the API rather than inferred: circular references are rejected outright,
the compiled grammar has a size budget, `oneOf` is unsupported, and there is a cap on
union-typed parameters. Stratifying the grammar into acyclic levels, requiring every
property, stripping descriptions and numeric constraints, and flattening the predicate
union each moved a wall — and the best that fits is a **depth-2** predicate tree, which
cannot express the nested correlation the pivots exist to serve.

So translation is unconstrained generation, validated afterwards. That is fine: over ten
questions, **Opus 5 compiled 9/10 first try**, and **Haiku 4.5 reached 7/10 with one
repair turn** at **5.6× lower cost**. Both models get the shape wrong in the same
harmless way — they return the predicate tree as a JSON *string* — which a coercing parse
fixes deterministically.

The probing also turned up a **gap in the grammar itself**: an aggregate or ordering key
cannot reach a value under a repeated level, so *"the ten highest-yielding reactions"* is
unwritable. Both models tried it, and repair does not help, because nothing they could
have written would have worked.

## Method

Every claim here is a live call against the Messages API, using the key the interface
deployment already holds (`ord-interface-anthropic-api-key`). The probes are in
[`assets/`](assets/README.md); the schema transforms they use — stratification and the
all-required rewrite — are the interesting half and are worth reading before repeating
this work.

Ten questions were used throughout, from single-predicate (`reactions run above 350 K`)
to correlated (`pyridine as the solvent with a yield above 50%`) to aggregate (`the ten
highest-yielding Suzuki couplings`). A translation is scored on whether it validates
against the pydantic models and then compiles, which is a stricter bar than "looks right"
and a weaker one than "returns the right reactions" — result-level scoring wants an eval
set, which the design proposes and this entry does not have.

## Findings

### 1. The recursive grammar is refused by every constrained path

`Query`'s predicate tree is recursive: `and`/`or` hold clauses, `not` holds a clause, and
a quantifier's body may hold another quantifier. Pydantic renders that as 12 definitions
with 134 internal references, 2,431 tokens.

| path | result |
| --- | --- |
| `output_config.format` (structured outputs) | `Circular reference detected in schema definitions: And -> And` |
| tool with `strict: true` | same refusal |
| tool without `strict` | **accepted** |

The SDK is not the obstacle: it sends the recursion faithfully, and its transform has
deliberate handling for `$defs` and root-level `$ref`. The refusal is server-side, and
the [structured outputs documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
confirms recursive schemas are unsupported.

### 2. Removing the recursion does not help, because the wall behind it is smaller

The grammar can be made acyclic without changing the IR: stratify it, so a level-*k*
predicate's clauses are level-*(k-1)* predicates and level 0 holds only leaves. Nothing is
inlined, so size grows by about **1,400 tokens per level** rather than by a power of four
— naive inlining reaches 331,086 tokens at depth 5, stratification 9,274.

That clears the cycle and immediately hits the next wall:

| depth | schema | `output_config.format` | strict tool |
| --- | --- | --- | --- |
| 0 | 2,425 tok | accepted | too large |
| 1 | 3,944 tok | too large | too large |
| 2 | 5,415 tok | too large | too large |
| 4 | 8,359 tok | too large | too large |

Depth 0 is a single leaf predicate: no boolean, no quantifier. The strict-tool path is
tighter still and fits nothing.

### 3. The budget is union-typed parameters, not tokens

A [reported limit](https://github.com/anthropics/anthropic-sdk-python/issues/1185) says
optional properties roughly double the compiled state machine. Requiring every property
and expressing optionality as an explicit null takes the grammar from 13–17 optional
properties to zero and shrinks it by a third — and then two more walls appear in turn:
`oneOf` is unsupported (pydantic emits it for the discriminated union; rewriting to
`anyOf` is safe, since the models validate afterwards), and numeric constraints like
`exclusiveMinimum` are rejected.

Past those, depth 0 fits at 1,000 tokens and depth 1 does not, at 1,653. The error
changes to *"too many parameters with union type"*, which names the real budget: every
nullable field is a union, and each level multiplies them.

### 4. What does fit is a flat predicate at depth 2 — with every path enumerated

Collapsing the eight predicate variants into one object whose `op` selects the shape, and
making `path` an enum, buys the most room. The enum turns out to be nearly free:

| paths enumerated | depth 2 | depth 3 | depth 4 |
| --- | --- | --- | --- |
| free-form string | accepted | refused | refused |
| 40 | accepted | refused | refused |
| 120 | accepted | refused | refused |
| **all 431 scalar paths** | **accepted** (15,240 tok) | refused | refused |

The enumeration is the 431 scalar paths `probe_flat_union.py` walks to, which skips the
key side of a map; the schema rendering counts 442 leaves and 537 lines because it carries
those too.

This is worth remembering rather than building. Enumerating the paths makes an invented
column *structurally impossible*, and invented columns are the cheap model's main failure
mode. But depth 2 cannot nest a quantifier inside a quantifier, so correlated questions —
the ones the pivoted element index exists to answer — fall outside it.

### 5. Unconstrained, both models write the tree as a string

Given a non-strict forced tool call, the model reliably returns:

```json
{"where": "{\"op\": \"and\", \"clauses\": [ ... ]}"}
```

The predicate tree arrives JSON-encoded inside a string, and pydantic rejects it. Opus did
this on 4 of 5 questions, Haiku on 5 of 5. Parsing string values back to objects before
validating takes both to 5/5 — this is the one thing a strict schema would have bought,
and it costs about ten lines to do without one.

### 6. Opus 9/10, Haiku 7/10 with repair, at 5.6× the cost

Ten questions, scored on compiling; a failure is handed back once with the compiler's own
error, which names the offending path and suggests a real one.

| model | first try | after one repair | ~cost per query |
| --- | --- | --- | --- |
| Claude Opus 5 | 9/10 | 9/10 | 1.3¢ |
| Claude Haiku 4.5 | 5/10 | 7/10 | **0.23¢** |

Haiku's failures are inventions of syntax the grammar does not have — `identifiers[*].value`,
`inputs[].components` — rather than misunderstandings of the question. Repair recovers two
of them. That is the failure mode finding 4 would eliminate outright, which is why the
path enum is worth keeping in mind for shallow queries.

Cost is dominated by the cached prefix: the schema rendering plus the grammar is **15,481
tokens on Opus, 11,462 on Haiku**, read at a tenth of list price on every call after the
first. Caching mattered more than model choice.

### 7. The grammar cannot order by a value under a repeated level

Opus's single failure, unrepairable and shared with Haiku:

```text
outcomes.products.measurements.percentage.value: max needs a scalar column, not a repeated level
```

`Measure` and `Order` require a scalar path, and a yield lives under `outcomes` →
`products` → `measurements`. "The ten highest-yielding reactions" needs a per-reaction
reduction of a repeated path — `max` over each reaction's measurements — and there is no
way to write one. Both models reached for it independently, which is the strongest signal
available that the gap is real rather than a prompting artifact.

## Conclusions / next steps

Translation is unconstrained generation checked afterwards, and the design that follows
from that is [beside this entry](assets/nl-search-design.md): one forced tool call over
the recursive grammar with the prefix cached, a coercing parse, one repair turn carrying
the compiler's error, then execution and a short second call that writes the prose.

Three things to do in order:

1. **Close the reduction gap** (finding 7). It is a grammar change, it blocks a question
   anyone would ask, and the NL layer would otherwise paper over it with a wrong answer.
2. **Build the layer**, with the model as configuration rather than a decision — the
   measured 9/10 and 7/10 are ten questions, not an eval set.
3. **Then choose the model on evidence**, including whether path guidance in the cached
   prefix closes Haiku's gap. At 5.6× it is worth the measurement.

## References

- [`assets/nl-search-design.md`](assets/nl-search-design.md) — the design this entry argues for
- [`assets/nl-search-plan.md`](assets/nl-search-plan.md) — the task-by-task plan built from it
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) — recursion unsupported; limits undocumented
- [anthropic-sdk-python#1185](https://github.com/anthropics/anthropic-sdk-python/issues/1185) — the optional-property state-space report
- [ord-schema#966](https://github.com/open-reaction-database/ord-schema/pull/966) — the split that renamed `agent` to `search`
- [Where the agent search cache can live](../2026-08-15-where-the-search-cache-lives/README.md) — the pivots and index this layer queries through
