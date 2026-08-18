# Scripts for "What constrains a natural-language layer over the search grammar"

- **Date:** 2026-08-17
- **Author:** Steven Kearnes
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Probes for [the entry beside them](../README.md), the design they argue for
([`nl-search-design.md`](nl-search-design.md)), and the plan that implements it
([`nl-search-plan.md`](nl-search-plan.md)).

Every probe but the first makes live Messages API calls. Run them with `ord_schema`
importable and a key in the environment; the interface deployment's key works, and is
where these numbers came from:

```bash
export ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
    --secret-id ord-interface-anthropic-api-key --query SecretString --output text)
uv run --with anthropic python probe_repair.py claude-haiku-4-5
```

| script | what it measures | finding |
| --- | --- | --- |
| `probe_recursion.py` | what the SDK puts on the wire for a recursive model, via a mock transport — no key needed | 1 |
| `probe_recursion_live.py` | whether `output_config.format` accepts the recursive grammar | 1 |
| `probe_tool_recursion.py` | the same question for tool schemas, strict and not | 1, 5 |
| `probe_shapes.py` | how often a forced tool call parses as written, and after coercion | 5, 6 |
| `probe_stratified.py` | whether an acyclic grammar unlocks structured outputs | 2 |
| `probe_bisect.py` | which construct exhausts the compiled-grammar budget | 2, 3 |
| `probe_strict_tool.py` | whether the strict-tool path has a larger budget | 2 |
| `probe_required.py` | whether requiring every property fits the budget | 3 |
| `probe_flat_union.py` | a flattened predicate with paths enumerated, by depth | 4 |
| `probe_repair.py` | first-try and after-repair accuracy, per model, with cost | 6, 7 |

Two of these are library rather than probe, and are the reusable part:

- `stratify.py` turns a recursive JSON Schema into an acyclic one by numbering levels —
  a level-*k* definition references level *(k-1)*, and level 0 drops the recursive
  branches. Nothing is inlined, so size grows per level rather than per power.
- `require_all.py` makes every property required with an explicit null instead of
  optional, rewrites `oneOf` to `anyOf`, and drops keywords a decoder rejects. Optional
  properties are what multiply the compiled state machine.

Both transform only the schema *shown to the model*. The pydantic models are untouched and
still do the validating, which is why dropping `exclusiveMinimum` and the discriminator
costs no correctness.

`probe_repair.py` takes a model id as its argument and is the one to re-run when the
prompt changes; it prints per-question outcomes, first-try and after-repair tallies, and
the token counts the cost figures come from. Costs in the entry are computed from those
counts at list price, with cached reads at a tenth.
