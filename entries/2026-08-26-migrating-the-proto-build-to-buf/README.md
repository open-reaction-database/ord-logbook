# Migrating the proto build to buf

- **Date:** 2026-08-26
- **Author:** Steven Kearnes
- **Status:** draft (plan; nothing implemented)
- **Tags:** ord-schema, protobuf, buf, ci, tooling, schema-evolution
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`compile_proto_wrappers.sh` hand-pins five tools to produce four kinds of generated
output, and CI reinstalls all five by URL and checksum on every run. Separately, nothing
anywhere catches a wire-breaking edit to `reaction.proto`. Is buf worth adopting, which
parts of it, and what does the migration actually involve?

## Summary

**Adopt three of buf's four parts. `buf breaking` is the reason to do this, the BSR is
what makes the schema usable by people who never contact us, and `buf generate` is a
cleanup that rides along. `buf lint` has to be configured mostly off.**

- **`buf breaking` is the whole argument.** Field numbers and `reserved` ranges are what
  make protobuf the right choice for an archive that has to stay parseable for decades —
  and today that discipline is enforced by reviewer attention alone. Nothing detects a
  renumbered field, a changed type, or a deletion without `reserved`. This is the one
  capability the current setup has no substitute for.
- **`buf generate` replaces a hand-pinned toolchain.** Today CI installs protoc 22.3,
  protobuf-javascript 3.21.2, ts-protoc-gen 0.15.0, protobufjs 7.4.0, and
  protobufjs-cli 1.1.3 — two by URL plus sha256, three by npm — before it can run the
  build script. A `buf.gen.yaml` with pinned remote plugins collapses most of that.
- **`buf lint` is not a candidate.** `reaction.proto` deliberately violates the enum
  style guide, and says so at the top of the file: enums are nested rather than prefixed
  so that `CUSTOM` and `UNSPECIFIED` are unqualified values across every enum. The rules
  that would fire (`ENUM_VALUE_PREFIX`, `ENUM_ZERO_VALUE_SUFFIX`) would demand renaming
  every enum value in the public API. Configure them off; do not "fix" the schema.
- **Publish to the BSR, and treat it as outreach rather than as a response to demand.**
  A hosted module gives the schema a browsable reference page built from the comments
  already in `reaction.proto`, and lets anyone generate an SDK for their language without
  ORD maintaining one. It also improves the breaking check: `buf breaking` can compare
  against the last *published* version rather than only against `main`, which closes the
  gap where a break is introduced and then compounded across several merged PRs.
- **`buf generate` cannot cover everything.** `pbjs`/`pbts` read `.proto` files directly
  rather than acting as protoc plugins, so `js/ord-schema-protobufjs/` stays a shell step
  no matter what. Whether the `protoc-gen-js` and `ts-protoc-gen` outputs can move is the
  open question that gates the codegen stage — Google archived protobuf-javascript, and
  the plan does not assume a maintained remote plugin exists for it.
- **Staging matters.** Stage 1 (`buf breaking`) and stage 2 (BSR) change no generated
  bytes and can land on their own. Stage 3 (`buf generate`) touches committed output that
  a CI drift check compares byte-for-byte, so it needs plugin versions pinned to today's
  exact versions or it lands as a large and uninformative diff.

## Current state

Generated code is committed — 29 tracked files under `ord_schema/proto/` and `js/` — and
[`run_tests.yml`](https://github.com/Open-Reaction-Database/ord-schema/blob/main/.github/workflows/run_tests.yml)'s
`test_proto_wrappers` job regenerates everything and fails on any drift, ignoring only
the copyright line. So the committed output is already verified against the `.proto`
files on every PR. That check is good and stage 2 must preserve it.

What produces what, from
[`compile_proto_wrappers.sh`](https://github.com/Open-Reaction-Database/ord-schema/blob/main/compile_proto_wrappers.sh):

| output | produced by | pinned at |
|---|---|---|
| `ord_schema/proto/*_pb2.py` | `protoc --python_out` | protoc 22.3 |
| `ord_schema/proto/*_pb2.pyi` | `protoc --pyi_out` | protoc 22.3 |
| `js/ord-schema/proto/*_pb.js` | `protoc --js_out` (protobuf-javascript) | 3.21.2 |
| `js/ord-schema/proto/*_pb.d.ts` | `protoc --ts_out` (ts-protoc-gen) | 0.15.0 |
| `js/ord-schema-protobufjs/index.js`, `index.d.ts` | `pbjs` / `pbts` | protobufjs-cli 1.1.3 |

The Python runtime is a separate pin: `protobuf>=4.22.3,<6` in `pyproject.toml`,
currently resolving to upb 5.29.6.

## What each piece buys

**`buf breaking --against '.git#branch=main'`.** Compares the PR's schema against main
and fails on wire-incompatible changes: reused or renumbered field tags, changed field
types, fields or enum values deleted without `reserved`, changed cardinality. This is new
capability, not a reorganization of existing capability. It is also the piece that
matters most given how the schema is used — every `.pb.gz` and `.parquet` in ord-data is
parsed by field number, so a renumbering silently changes what old records mean rather
than failing loudly.

**`buf generate`.** A declarative `buf.gen.yaml` naming plugins and versions, replacing
both the shell script and the install block in CI. Remote plugins run on buf's
infrastructure, so contributors need neither protoc nor the JavaScript plugins installed
to regenerate. The trade is a network dependency in CI where there is currently a
checksummed download.

**`buf lint` / `buf format`.** Skip. See the enum discussion above; `buf format` would
also reflow a 1341-line file that has years of hand-placed comments in it.

**BSR.** A hosted registry holding the module at a versioned path. Three things it gives
a public schema that a GitHub repository does not: a browsable reference page generated
from the comments already in `reaction.proto`; on-demand SDK generation, so someone
working in Go or C# gets typed bindings without ORD maintaining a build for their
language; and a published version to check against, which is a better `buf breaking`
baseline than `main`.

It is free at the scale that matters here. Buf's [Community
tier](https://buf.build/pricing) allows unlimited public repositories, and types in
public repositories do not count toward billable types — billing is per message, enum,
and RPC in *private* repositories. An Apache-2.0 schema published publicly costs nothing.

The costs are non-monetary and worth naming anyway:

- **Someone has to own the organization.** A `buf.build/open-reaction-database` org needs
  an admin, and for a community project, admin succession is a real question rather than
  a formality. Decide who holds it before publishing, not after.
- **The module path is effectively permanent.** Once people depend on it, renaming or
  deleting the module breaks them. The path is a one-time decision.
- **A token in CI.** Publishing on merge needs a BSR token as a repository secret, with
  the usual rotation question attached.
- **An SDK is not the library.** Generated bindings carry the message types and nothing
  else — no validation, no `smiles_from_compound`, no unit normalization. The reference
  page should say so plainly, or the BSR listing will imply a level of support that does
  not exist.

## Plan

Stages 1 and 2 are independent of the plugin question and of each other's risk; stage 3
is the only one gated on stage 0. Order them 1 → 2 → 3 anyway, so the breaking check is
in place before anything is published that others might depend on.

**Stage 0 — settle the plugin question (gate for stage 3).** Check whether buf's remote
plugin catalog carries `protocolbuffers/js` and a TypeScript declaration plugin
equivalent to ts-protoc-gen, at versions matching 3.21.2 and 0.15.0. protobuf-javascript
is archived upstream, so a maintained remote plugin may not exist. Outcomes: all four
protoc outputs move (stage 3 as written); only Python and `.pyi` move (stage 3 covers
those, the JS outputs stay on local protoc); or nothing moves cleanly (drop stage 3, keep
stages 1 and 2). Do this before writing any config — it decides how much of stage 3
exists.

**Stage 1 — `buf breaking` in CI.** Independent of stage 0 and worth doing regardless.

1. Add a minimal `buf.yaml` declaring the module at `proto/`, with `lint` restricted to
   the rules the schema actually honors — or disabled outright, with a comment pointing at
   the enum-nesting rationale in `reaction.proto` so nobody re-enables it and starts
   renaming enum values.
2. Add a CI job running `buf breaking --against '.git#branch=main'`. Full history is
   needed for the `.git` input, so the checkout needs `fetch-depth: 0`.
3. Verify it actually fires: on a scratch branch, renumber a field and confirm the job
   fails; delete a field without `reserved` and confirm the same.

Step 3 is the point of the stage. A breaking-change check that has never been seen to
fail is indistinguishable from one that is misconfigured.

**Stage 2 — publish to the BSR.** Independent of stage 0. Do it after stage 1, so the
breaking check is guarding the schema before anyone can depend on the published module.

1. Decide the organization and module path, and who administers the org. This is the
   irreversible part; everything after it is mechanical.
2. Claim `buf.build/open-reaction-database` and create a public module for `proto/`.
3. Push from CI on merge to main, using a BSR token stored as a repository secret.
4. Tag published versions to match ord-schema releases, so a consumer can pin to the same
   version they pin the Python package to. Unreleased commits stay reachable without a
   tag; releases get one.
5. Once a tagged version exists, add a second `buf breaking` job comparing against the
   published release rather than `main`. This is the one that catches a break introduced
   and then compounded across several merged PRs, which the `main` comparison cannot.
6. Write the module description to say what the SDKs do and do not include — types yes,
   validation and derivation no, with a pointer to the Python package for those.

**Stage 3 — `buf generate` (conditional on stage 0).**

1. Write `buf.gen.yaml` pinning each plugin to the *exact* version in use today, so the
   regenerated output is byte-identical and the drift check passes unchanged.
2. **Disable managed mode.** It rewrites file options, which would change generated
   output for no reason anyone reviewing the diff could act on.
3. Keep the `pbjs`/`pbts` step as a shell step — those are not protoc plugins and cannot
   move into `buf generate`.
4. Replace the install block in `test_proto_wrappers` with `setup-buf`, keeping whatever
   local toolchain the leftover steps still need.
5. Confirm the drift check passes with no changes to committed generated files. If it
   does not, stop and find out why before regenerating: a diff here means the toolchain
   moved, and that should be a separate, deliberate commit.
6. Bump plugin versions only afterward, as its own change, so the version bump's diff is
   readable on its own.

## Risks and open questions

- **Archived JS plugin.** The stage 0 gate. If `protoc-gen-js` has no maintained remote
  plugin, part of the toolchain stays hand-pinned and stage 3's value shrinks
  accordingly. That is an acceptable outcome, not a blocker — stages 1 and 2 carry the
  value.
- **Generated-output drift.** Buf compiles with its own implementation rather than
  shelling out to protoc. Even at a matching plugin version the descriptor bytes embedded
  in `*_pb2.py` could differ. Stage 3 step 5 is where this surfaces; treat any diff as a
  finding to understand, not a diff to accept.
- **Network dependency.** Remote plugins mean CI codegen depends on buf.build being
  reachable, where today it depends on GitHub release URLs. Local plugins are the
  fallback if that matters. Publishing to the BSR adds the same dependency to the release
  path, though a failed push is visible and retryable rather than silent.
- **Publishing raises the stakes on breakage.** Today a wire-breaking edit hurts ORD's own
  consumers. Once the module is on the BSR and advertised, it hurts people who never
  talked to us. That is the point of doing stage 1 first, and the reason stage 2's second
  breaking job — comparing against the last published release — is part of the stage
  rather than a later nicety.
- **A public module invites questions.** SDK generation is free to us and not free to
  ignore: people will file issues against a schema they generated bindings from. Worth
  expecting rather than being surprised by.
- **What `buf breaking` does not check.** Semantic compatibility. Redefining what an
  existing field *means*, tightening a validation rule, or changing a unit convention are
  all wire-compatible and all breaking. The check raises the floor; it does not replace
  review.

## Conclusions / next steps

1. Run stage 0 — a catalog lookup, not a code change.
2. Settle who owns the buf.build organization. It gates stage 2 and is a people question,
   so start it early rather than discovering it at publish time.
3. Land stage 1 regardless of the plugin answer. It is small, it is additive, and it
   closes the one gap the current setup has no answer for.
4. Land stage 2 once stage 1 is guarding the schema.
5. Land stage 3 only if stage 0 comes back clean, and keep the version bump separate from
   the migration.

Explicitly not in scope: changing enum naming to satisfy `buf lint`, publishing
hand-maintained C++ or Rust bindings — the BSR generates those on demand, which is the
point — and `protovalidate`. That last one is the schema's real missing capability:
validation rules live in 1511 lines of Python that no other language gets, so an SDK
generated from the BSR carries types without the rules that make a dataset valid. It is a
much larger decision than the build tooling, and coupling the two would make both harder
to review.

## References

- [ord-schema](https://github.com/Open-Reaction-Database/ord-schema) —
  `compile_proto_wrappers.sh`, `proto/reaction.proto`, and the `test_proto_wrappers` job
  in `.github/workflows/run_tests.yml`.
- [buf documentation](https://buf.build/docs) — `buf.yaml`, `buf.gen.yaml`, and the
  breaking-change rule categories.
- [Buf pricing](https://buf.build/pricing) — the Community tier's unlimited public
  repositories, and [manage costs](https://buf.build/docs/subscription/manage-costs/) for
  the statement that public-repository types are not billable.
- [protobuf-javascript](https://github.com/protocolbuffers/protobuf-javascript) — the
  archived plugin behind the stage 0 gate.
- Prior entry:
  [2026-08-02-validation-performance/](../2026-08-02-validation-performance/README.md) —
  where the validation rules live and why a rewrite in another language is not the answer.
