# How much of ord-schema's validation could protovalidate carry?

- **Date:** 2026-10-02
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** final
- **Tags:** ord-schema, validation, protovalidate, buf, schema
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

Every rule that makes an ORD record valid lives in `ord_schema/validations.py`, 1,511
lines of Python. Code generated from the schema in any other language — the npm
packages, anything built from the BSR module — gets the types and none of the rules.
[protovalidate](https://protovalidate.com) moves rules into the `.proto` files as
annotations, which each language's runtime then enforces.
[The buf migration entry](../2026-08-26-migrating-the-proto-build-to-buf/README.md)
left it out of scope as a larger decision than the build tooling.

This is the first measurement that decision needs: of the checks `validations.py`
makes, how many could protovalidate express, and in what form?

## Summary

**Most of them, mostly in CEL, and none of the warnings as warnings.**

Of the 102 places `validations.py` records a finding (62 errors, 40 warnings):

| route | what it is | errors | warnings | sites | rule instances |
| --- | --- | ---: | ---: | ---: | ---: |
| field | a standard rule on one field: required, pattern, range, min items | 23 | 7 | 30 | 81 |
| CEL | a message-level CEL expression: conditional, cross-field, or over the message's subtree | 31 | 30 | 61 | 116 |
| code | needs RDKit, a free-form date parser, or checksum arithmetic | 6 | 3 | 9 | 10 |
| dataset | compares reactions across a dataset | 2 | 0 | 2 | 2 |

So 91 of the 102 could be written as protovalidate rules, and 30 of those as plain field
annotations without CEL. Three things keep that from being the whole story:

- **protovalidate has no severity.** A violation is a failure. All 40 warnings — 37 of
  them otherwise expressible — would either fail validation, need a convention layered
  on top, or stay in Python. The `SUGGESTION` level proposed in
  [ord-schema#1069](https://github.com/open-reaction-database/ord-schema/pull/1069)
  widens the gap.
- **The 11 code and dataset checks stay in Python whatever happens.** They are the ones
  closest to chemistry: whether a structure parses, whether a compound's identifiers
  agree, whether a reaction SMILES is valid.
- **Rules are fixed in the schema, and five checks are not.** `validate_ids`,
  `require_provenance`, and `allow_reaction_smiles_only` switch them per call.

## Method

- Every `context.error` and `context.warn` call in `ord_schema/validations.py` at
  ord-schema `9b6a16b` (the module last changed in `945e17d`), one row each, in
  [`checks.csv`](assets/checks.csv): the line, the validator, the severity, what it
  checks, the route, how many message types it runs on, and any option that switches it.
- [`tally.py`](assets/tally.py) produces the table above, and with
  `--validations path/to/validations.py` first confirms the CSV names every call site at
  its line and with its severity. It passes against `9b6a16b`.
- A shared helper is one row with an instance count: `_check_type_and_details` runs on
  27 message types, so its two checks would be 54 annotations in the schema.
- Routes were decided against protovalidate's
  [standard rules](https://protovalidate.com/schemas/standard-rules/) and its
  [`validate.proto`](https://github.com/bufbuild/protovalidate/blob/main/proto/protovalidate/buf/validate/validate.proto),
  and against where each message type appears in the schema. A rule belongs on a field
  only if it holds everywhere the field's message is used: `Person.email` is required on
  a `RecordEvent` and optional as `ReactionProvenance.experimenter`, so that check is
  CEL on `RecordEvent`, not a rule on `Person`.

## Findings

### 1. Thirty checks are plain field rules

The required fields — a unit message's `value` and `units`, a dataset's `name` and
`description`, an identifier's `value` — are `required` or `min_len`. The non-negativity
check is `gte: 0`, and it is the most repeated rule in the module: the value and precision
of 11 unit types, the precision of three more, a stirring rate, and two m/z bounds, 29
annotations from one helper. Formats are `pattern`: reaction and dataset IDs, email
addresses, URLs, and the DOI, whose "parses" and "has nothing around it" checks are
together one full-match pattern. `Data`'s "one of value, bytes, or URL" is a `oneof`
marked `required`.

Even "a percentage is not a fraction between 0 and 1" is a field rule: when `gte` exceeds
`lte`, protovalidate reverses the range and requires the value to fall outside it.

### 2. Sixty-one need CEL, and the most common reason is an empty message

Over half the CEL, 32 of the 61 checks, is conditional on an enum — a type, a role, or
units: a `WAIT` workup should have a duration, an `IDENTITY` measurement should have no
value, a CAS number should match its pattern only when the identifier is a CAS number.
These are short expressions.

The single most repeated check needs CEL for a less obvious reason.
`_check_type_and_details` — `type` is set, and `CUSTOM` has `details` — returns early for
an entirely empty message, on 27 message types. A standard rule cannot say "unless every
field is unset", so each of the 54 instances is CEL.

A few walk a subtree, which CEL can do and which makes for the longest rules: whether
every input component has an amount (a map of inputs, each a list of components, each
amount a `oneof`), whether an internal standard is used without a component in that
role, and whether every `analysis_key` names an entry in the outcome's `analyses` map.
The texture check writes a twelve-entry table of texture to state of matter into the
expression.

Two regular expressions would not match Python exactly. CXSMILES detection splits on
whitespace as Python's `str.split` does, which includes non-breaking spaces — and the
corpus has SMILES with trailing ones — where RE2's `\s` is ASCII only. And the PubChem
check uses `str.isdecimal`, which accepts non-ASCII digits that `[0-9]` does not.

Two checks repeat a third: `ReactionProvenance` requires an email on each record event's
person, and `RecordEvent` requires the same of its own.

### 3. Nine need code

| checks | needs |
| --- | --- |
| a structural identifier parses; it sanitizes; a compound's identifiers agree; a reaction SMILES parses | RDKit |
| a `DateTime` parses; provenance times parse; a record is created after its experiment and modified after it is created | `dateutil`, which reads free-form dates; CEL's `timestamp()` reads RFC 3339 only |
| an ORCID's check digit | ISO 7064 MOD 11-2 over 15 digits; CEL has no loops |

The ORCID format is a pattern; only the checksum is code.

### 4. Two compare reactions across a dataset

No two reactions share an ID, and every referenced reaction ID is defined. CEL on
`Dataset` could state both, but ORD validates large datasets a slice at a time
(`DatasetCrossRefState` merges the slices), and protovalidate sees one message. The third
cross-reference check, that a reaction does not reference itself, needs only the
reaction, so it is CEL.

### 5. Severity and options have no equivalent

Violations carry a field path, the rule that failed, a message, and a rule ID for CEL
rules, and nothing else. Of the checks that could move, 37 are warnings today. A
convention could recover the distinction — a rule-ID prefix the Python wrapper maps to
`Severity.WARNING`, say — but every other language's runtime would report them as
failures unless its caller knew the convention too.

The five option-dependent checks are the ID formats (`validate_ids`), the provenance
requirement (`require_provenance`), and the input and outcome requirements that a
reaction-SMILES-only record is exempt from (`allow_reaction_smiles_only`). A rule in the
schema cannot be switched per call, so each would be always on, always off, or left in
Python.

## Conclusions / next steps

**Recommendation: do not adopt it yet.** The measurement says protovalidate could carry
most of the rules, but its benefit lands entirely on non-Python consumers validating
records themselves, and none needs that today. ORD's submission pipeline validates in
Python, and so does ord-app's service: the editor shows the errors and warnings the
service records, and its own form rules check only that input, data, and analysis names
are unique. Adopting it now means maintaining the same rules twice,
or rewriting `validations.py` to delegate to protovalidate-python, for consumers that do
not exist.

What would change that:

- **A non-Python consumer that has to validate.** An editor validating client-side, or
  an outside group generating SDKs from the BSR and asking why their records fail ORD's
  checks.
- **A single source of truth worth the migration.** If `validations.py` delegated its
  91 expressible checks to protovalidate-python, the rules would live once, in the
  schema. That needs two measurements first: protovalidate-python's speed over the
  USPTO dataset, against today's validator, and a warning convention both ord-schema and
  any other runtime would honor.

If either arrives, the first step is the 23 field-rule errors: plain annotations with no
CEL, no severity question, and no option. They would show the cost of the BSR dependency
and the annotation style before anything harder is attempted.

## References

- [`assets/checks.csv`](assets/checks.csv) and [`assets/tally.py`](assets/tally.py) — the
  inventory and the tally above.
- ord-schema [`ord_schema/validations.py`](https://github.com/open-reaction-database/ord-schema/blob/9b6a16b/ord_schema/validations.py)
  at `9b6a16b`.
- [Migrating the proto build to buf](../2026-08-26-migrating-the-proto-build-to-buf/README.md)
  — where protovalidate was left out of scope.
- protovalidate [standard rules](https://protovalidate.com/schemas/standard-rules/) and
  [`validate.proto`](https://github.com/bufbuild/protovalidate/blob/main/proto/protovalidate/buf/validate/validate.proto).
- [ord-schema#1069](https://github.com/open-reaction-database/ord-schema/pull/1069) —
  the proposed `SUGGESTION` level.
