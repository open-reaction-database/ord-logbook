# Migrating the proto build to buf

- **Date:** 2026-08-26
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5, Claude Opus 5.5)
- **Status:** draft (stages 0, 1, and 3 done; stage 2 published with v0.9.0, its breaking job against the release still to land)
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
- **`buf lint` is not a candidate, and the reason is stronger than "we deviate."** buf's
  defaults are stricter than the upstream style guide, which permits nesting outright,
  and the collision `ENUM_VALUE_PREFIX` guards against is one protoc has already
  prevented. Configure the rule off; do not "fix" the schema. Measured below.
- **Publish to the BSR, and treat it as outreach rather than as a response to demand.**
  A hosted module gives the schema a browsable reference page built from the comments
  already in `reaction.proto`, and lets anyone generate an SDK for their language without
  ORD maintaining one. It also improves the breaking check: `buf breaking` can compare
  against the last *published* version rather than only against `main`, which closes the
  gap where a break is introduced and then compounded across several merged PRs.
- **`buf generate` cannot cover everything, and stage 0 measured how much.** Python,
  `.pyi`, and JavaScript all have remote plugins at exactly today's versions;
  `ts-protoc-gen` has none and stays a local plugin, and `pbjs`/`pbts` read `.proto`
  directly rather than acting as protoc plugins so they stay a shell step regardless. Net
  saving: the two checksummed archive downloads go, the three npm installs stay.
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

[ord-schema#1033](https://github.com/open-reaction-database/ord-schema/pull/1033) moves
the sources from `proto/` to `proto/ord-schema/proto/` without changing any of these
paths; stage 1 below says why.

## What each piece buys

**`buf breaking`.** Compares the PR's schema against main and fails on incompatible
changes: reused or renumbered field tags, changed field types, deleted fields or enum
values, changed cardinality. Under the `FILE` category ord-schema configures, that
includes source-level breaks too — a rename, or a deletion even with its number and name
reserved — because consumers import the generated names. This is new
capability, not a reorganization of existing capability. It is also the piece that
matters most given how the schema is used — every `.pb.gz` and `.parquet` in ord-data is
parsed by field number, so a renumbering silently changes what old records mean rather
than failing loudly.

**`buf generate`.** A declarative `buf.gen.yaml` naming plugins and versions, replacing
both the shell script and the install block in CI. Remote plugins run on buf's
infrastructure, so contributors need neither protoc nor the JavaScript plugins installed
to regenerate. The trade is a network dependency in CI where there is currently a
checksummed download.

**`buf lint` / `buf format`.** Skip. See the enum section below; `buf format` would also
reflow a 1341-line file that has years of hand-placed comments in it.

## Why `ENUM_VALUE_PREFIX` stays off

The rule buf would apply is not the rule protobuf.dev states. The
[style guide](https://protobuf.dev/programming-guides/style/#enums) says "either option
is enough to mitigate collision risks, but prefer top-level enums with prefixed values
over creating a message simply to mitigate the issue" — nesting is permitted, and the
preference is scoped to messages created *solely* to scope an enum. Auditing the
descriptors, 42 messages hold a nested enum: 28 carry substantive fields beyond
`type`/`details`, 13 are `{type, details}` pairs where `details` is the escape hatch
`CUSTOM` needs, and exactly one — `ord.ReactionRole` — has no fields at all. One case out
of 42 matches the pattern the guide advises against.

Three measurements say prefixing would cost something real and buy nothing:

- **`protoc` already emits the prefix for C++.** Generating `--cpp_out` from both
  schemas, today's nested enum produces `CompoundIdentifier_CompoundIdentifierType_SMILES`
  at namespace scope plus a `CompoundIdentifier::SMILES` in-class alias. Prefixing in
  source yields `CompoundIdentifier_CompoundIdentifierType_COMPOUND_IDENTIFIER_TYPE_SMILES`
  — 72 characters saying "compound identifier type" twice. C++ is the language the rule
  exists for, and nesting is what already solves it there.
- **Rust is indifferent, by design.** `prost-build` upper-camels each value and then
  strips a prefix matching the enum name, with `strip_enum_prefix: true` as the default.
  Both schemas generate `CompoundIdentifierType::Smiles`. The only divergence is for a
  consumer who calls `retain_enum_prefix()`, and it runs against prefixing.
- **The uniform spelling is load-bearing in Python.** `_check_type_and_details` reads
  `message.UNSPECIFIED` and `message.CUSTOM` off whatever it is handed, and 28 message
  types route through it. Prefixing replaces one generic check with a per-enum lookup;
  the type checker rejects the change immediately.

The cost of renaming is in
[ord-schema#992](https://github.com/open-reaction-database/ord-schema/pull/992). For the
most-referenced enum it is 33 attribute references, 161 string-form references across 21
files — six of them library modules, one inside raw SQL where nothing checks it — 1,059
lines in one fixture, and an 8.3% growth in the model-facing projection schema from a
single enum of roughly 100.

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
- **A token in CI.** Publishing needs a BSR token as a repository secret, with the usual
  rotation question attached. The public tier offers no token-less alternative: bot users
  and their GitHub OIDC trust credentials exist only on self-hosted and dedicated
  instances.
- **An SDK is not the library.** Generated bindings carry the message types and nothing
  else — no validation, no `smiles_from_compound`, no unit normalization. The reference
  page should say so plainly, or the BSR listing will imply a level of support that does
  not exist.

## Stage 0 result: which plugins exist

Checked against [`bufbuild/plugins`](https://github.com/bufbuild/plugins), which holds
the definition of every remote plugin the BSR serves. That repository rather than the BSR
web pages, which are client-rendered and return an empty shell to anything but a browser.

| output | remote plugin | today's version available? |
|---|---|---|
| `*_pb2.py` | `buf.build/protocolbuffers/python` | **yes** — `v22.3` |
| `*_pb2.pyi` | `buf.build/protocolbuffers/pyi` | **yes** — `v22.3` |
| `*_pb.js` | `buf.build/protocolbuffers/js` | **yes** — `v3.21.2` |
| `*_pb.d.ts` | none | **no** — see below |
| `protobufjs` bundle | n/a | not a protoc plugin |

**Three of four move at exactly today's version**, which is what stage 3 step 1 needs to
keep the drift check quiet. The `js` plugin's own definition even declares
`import_style=commonjs` and `binary` as its default options — the same pair
`compile_proto_wrappers.sh` passes to `--js_out`.

**The `--ts_out` gap is real.** Searching the whole plugin repository for `ts-protoc-gen`
and for `improbable` returns zero hits. The community org carries `stephenh-ts-proto` and
`timostamm-protobuf-ts`, but those are different generators producing different output,
not drop-in replacements for the `.d.ts` files ts-protoc-gen emits alongside the
protobuf-javascript output. Substituting one would change the published TypeScript API,
which is a separate decision from moving the build to buf.

`buf.gen.yaml` can invoke a local plugin binary beside remote ones, so ts-protoc-gen
stays in the build as a local plugin. Stage 3 is therefore worth doing, at a smaller
saving than first assumed: it removes the two checksummed archive downloads — protoc 22.3
and protobuf-javascript 3.21.2 — and leaves the three npm installs (ts-protoc-gen 0.15.0,
protobufjs 7.4.0, protobufjs-cli 1.1.3) in place.

**Correction to the earlier assumption.** This entry originally justified the gate by
saying Google had archived protobuf-javascript. That is wrong:
[the repository](https://github.com/protocolbuffers/protobuf-javascript) is not archived,
it was updated this month, and its latest release is v4.0.2 from February 2026. The
plugin that turned out to be missing was the one treated as the lesser risk.

## Plan

Stages 1 and 2 are independent of the plugin question and of each other's risk; stage 3
is the only one gated on stage 0. Order them 1 → 2 → 3 anyway, so the breaking check is
in place before anything is published that others might depend on.

**Stage 0 — settle the plugin question (gate for stage 3). DONE; see the section below.**
Three of the four protoc outputs have remote plugins at exactly today's versions. The
fourth, `--ts_out`, has none and runs as a local plugin instead.

**Stage 1 — `buf breaking` in CI. DONE.** Independent of stage 0 and worth doing regardless.

1. Give the schema an import root inside the repository. `dataset.proto` imports
   `ord-schema/proto/reaction.proto`, resolved through `--proto_path=..` from the parent
   of the checkout, which no buf module can reach. The sources move to
   `proto/ord-schema/proto/` with `proto/` as the root, which keeps that import path and
   every generated file byte-identical: protoc spells the hyphen as an underscore for
   Python, so the modules stay `ord_schema.proto.*_pb2`, and the JavaScript lands in
   `js/ord-schema/proto/`. Those files reach each other through `../../ord-schema/proto/`,
   which resolves in an installed package only because the directory shares the npm
   package's name — spelled `ord_schema`, `require('ord-schema')` fails — so CI installs
   the packed package, loads it, and typechecks its declarations. The same PR fixes a
   `pbjs` glob that has kept `Dataset` out of the protobufjs bundle. Landed in
   [ord-schema#1033](https://github.com/open-reaction-database/ord-schema/pull/1033).
2. Add a `buf.yaml` declaring the module at `proto/`. #1033 runs the `STANDARD` lint
   rules minus five, each excepted by name with its reason: `ENUM_VALUE_PREFIX` and
   `ENUM_ZERO_VALUE_SUFFIX` per the section above, `PACKAGE_DIRECTORY_MATCH` because
   step 1 keeps the existing import path rather than moving the sources under `ord/`,
   `PACKAGE_VERSION_SUFFIX` because it would rename every fully-qualified type, and
   `DIRECTORY_SAME_PACKAGE` because `test.proto` is package `ord_test`.
3. Add a CI job running `buf breaking --against '.git#ref=origin/main'`. Full history is
   needed for the `.git` input, so the checkout needs `fetch-depth: 0`, and the baseline
   is the remote-tracking ref: a pull-request checkout is a detached HEAD with no local
   `main`, so `#branch=main` fails on `couldn't find remote ref main` before reading the
   schema. buf comes from `bufbuild/buf-action` in setup-only mode, pinned to 1.72.0;
   `buf-setup-action` is archived. A deliberate break lands with a
   `breaking.ignore_only` entry in `buf.yaml`, keyed by rule and by path from the
   repository root, which comes out again once the change is on `main`. Landed in
   [ord-schema#1034](https://github.com/open-reaction-database/ord-schema/pull/1034).
4. Verify it actually fires: on a scratch branch, renumber a field and confirm the job
   fails; delete a field without `reserved` and confirm the same. Locally, a renumbered
   field, a deletion with or without `reserved`, and a changed field type each exit 100.
   In CI, scratch PR
   [ord-schema#1076](https://github.com/open-reaction-database/ord-schema/pull/1076)
   renumbered `DatasetExample.url` from 3 to 13 with the wrappers regenerated, and
   `test_proto_breaking` failed with exit 100 on `Previously present field "3" with name
   "url" on message "DatasetExample" was deleted`; the PR was closed unmerged.

Step 4 is the point of the stage. A breaking-change check that has never been seen to
fail is indistinguishable from one that is misconfigured.

**Stage 2 — publish to the BSR.** Independent of stage 0. Do it after stage 1, so the
breaking check is guarding the schema before anyone can depend on the published module.

1. Decide the organization and module path, and who administers the org. This is the
   irreversible part; everything after it is mechanical. The module is
   `buf.build/open-reaction-database/ord-schema`, matching the repository, the PyPI and
   npm packages, and the `ord-schema/proto/` import path. Admin succession is still open.
2. Claim `buf.build/open-reaction-database` — done 2026-10-01, by Steven Kearnes — and
   create a public module for `proto/`. Done.
3. Push from CI on release, using a BSR token stored as a repository secret. Pushing every
   merge would put unreleased schema under the module's default label, so a consumer who
   pins nothing could generate code that matches no published package. `publish.yml`'s
   `push_proto` job runs after `publish`, in its own job so buf and the token never share
   one with `id-token: write`, and pushes the newest `v*` tag in the repository: a release
   whose `gh release create` fails after the tag push still reaches the BSR, and a re-run of
   an older workflow cannot move `latest` back. The public tier has no bot users, so
   GitHub OIDC is unavailable; `BUF_TOKEN` is a limited-access token with `module.push` on
   this module only, issued from a maintainer's personal account. Landed in
   [ord-schema#1077](https://github.com/open-reaction-database/ord-schema/pull/1077).
   First exercised by
   [v0.9.0](https://github.com/open-reaction-database/ord-schema/releases/tag/v0.9.0) on
   2026-10-02, where that ordering mattered: the `publish` job failed after pushing the
   tag, because the `main` ruleset's bypass for `ord-service`'s maintain role applied only
   to pull requests, and `push_proto` published the release anyway.
4. Tag published versions to match ord-schema releases, so a consumer can pin to the same
   version they pin the Python package to. Each release is labeled with its tag, and
   `latest` follows the newest one, as npm's `latest` dist-tag does; `main` is not used,
   since it reads as the git branch. The module's default label moves from `main` to
   `latest` once the first release has created it: the BSR refuses a default label that
   does not exist yet. Done: the release is labeled `v0.9.0`, and the module's default
   label is `latest`. The two labels sit on different BSR commits —
   `latest` on one pushed a minute after the workflow's, from the same source commit —
   whose exported files are identical. The workflow pushed once; where the second push
   came from is unknown.
5. Once a tagged version exists, add a second `buf breaking` job comparing against the
   published release rather than `main`. This is the one that catches a break introduced
   and then compounded across several merged PRs, which the `main` comparison cannot.
6. Write the module description to say what the SDKs do and do not include — types yes,
   validation and derivation no, with a pointer to the Python package for those. Done:
   `proto/README.md` is the module page, and the repository's `LICENSE` applies through
   buf's workspace-root fallback.

**Stage 3 — `buf generate` (conditional on stage 0). DONE.**

1. Write `buf.gen.yaml` pinning each plugin to the *exact* version in use today, so the
   regenerated output is byte-identical and the drift check passes unchanged. Done in
   [ord-schema#1078](https://github.com/open-reaction-database/ord-schema/pull/1078): the
   Python and `.pyi` generators at v22.3 and protobuf-javascript at v3.21.2 as remote
   plugins, which run without BSR credentials, and ts-protoc-gen as a local plugin.
2. **Disable managed mode.** It rewrites file options, which would change generated
   output for no reason anyone reviewing the diff could act on. Measured: enabled with no
   overrides, it writes eight Java, C#, PHP, Ruby, and Objective-C options into every
   descriptor, none of which the Python or JavaScript generators read.
3. Keep the `pbjs`/`pbts` step as a shell step — those are not protoc plugins and cannot
   move into `buf generate`.
4. Replace the install block in `test_proto_wrappers`. What landed goes further than
   `buf-action`: a private `package.json` and `package-lock.json` at the repository root
   pin buf (as `@bufbuild/buf`), ts-protoc-gen, protobufjs, protobufjs-cli, and their
   dependencies, and `compile_proto_wrappers.sh` installs them with
   `npm ci --ignore-scripts` before generating. Contributors need only Node.js, every job
   that runs buf installs it from the same lockfile, and no workflow uses `buf-action`.
5. Confirm the drift check passes with no changes to committed generated files. If it
   does not, stop and find out why before regenerating: a diff here means the toolchain
   moved, and that should be a separate, deliberate commit. The JavaScript and TypeScript
   came out byte-identical; the three `*_pb2.py` files did not. Their embedded descriptors
   gained an explicit `json_name` on all 319 fields: protoc's built-in Python generator
   omits it, and the same generator run as a plugin writes what buf sends. Every value
   equals the camelCase name protobuf computes when the field is absent, the descriptors
   are otherwise identical, and the test suite passes, so #1078 regenerated them as a
   deliberate, explained change.
6. Bump plugin versions only afterward, as its own change, so the version bump's diff is
   readable on its own. The first bump,
   [ord-schema#1084](https://github.com/open-reaction-database/ord-schema/pull/1084), moved
   protobufjs to 7.6.6, protobufjs-cli to 1.3.3, and buf to 1.73.0. Only the protobufjs
   bundle regenerated differently, and it closed a bug in the published
   `ord-schema-protobufjs`: a map key named `__proto__` replaced the decoded map's
   prototype. The guard needs protobufjs 7.5.9 at runtime, so that package now requires
   `^7.6.6`. protobufjs 8 and protobufjs-cli 2 are left for a separate decision.

## Risks and open questions

- **`ts-protoc-gen` has no remote plugin.** Settled by stage 0 and not a blocker: it runs
  as a local plugin, which keeps its npm install in CI and shrinks stage 3's saving
  without changing its shape. Swapping to `ts-proto` or `protobuf-ts` would remove the
  local plugin but change the published TypeScript API, so it is a separate decision.
- **Version skew on a local plugin.** A remote plugin's version is pinned in
  `buf.gen.yaml` and resolved by buf; ts-protoc-gen's is pinned somewhere else. Settled
  by stage 3: the remote plugins live in `buf.gen.yaml` and every local tool in the root
  lockfile, which Dependabot proposes bumps for.
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

1. ~~Run stage 0.~~ Done — three of four outputs have exact-version remote plugins, and
   stage 3 survives with `ts-protoc-gen` as a local plugin.
2. ~~Settle who owns the buf.build organization.~~ Claimed 2026-10-01 by Steven Kearnes;
   the module path and admin succession are the open one-time decisions.
3. ~~Land stage 1.~~ Done — ord-schema#1033 and #1034, with the job seen failing in CI
   on #1076.
4. Stage 2: published. [v0.9.0](https://github.com/open-reaction-database/ord-schema/releases/tag/v0.9.0) reached the BSR as `v0.9.0` and `latest`, and `latest`
   is the module's default label. Step 5's breaking job against the release is what
   remains.
5. ~~Land stage 3.~~ Done — ord-schema#1078, with the first version bump separately in
   #1084.

Explicitly not in scope: changing enum naming to satisfy `buf lint`, publishing
hand-maintained C++ or Rust bindings — the BSR generates those on demand, which is the
point — and `protovalidate`. That last one is the schema's real missing capability:
validation rules live in 1511 lines of Python that no other language gets, so an SDK
generated from the BSR carries types without the rules that make a dataset valid. It is a
much larger decision than the build tooling, and coupling the two would make both harder
to review.

## References

- [ord-schema](https://github.com/Open-Reaction-Database/ord-schema) —
  `compile_proto_wrappers.sh`, `proto/ord-schema/proto/reaction.proto`, and the
  `test_proto_wrappers` job in `.github/workflows/run_tests.yml`.
- [buf documentation](https://buf.build/docs) — `buf.yaml`, `buf.gen.yaml`, and the
  breaking-change rule categories.
- [Buf pricing](https://buf.build/pricing) — the Community tier's unlimited public
  repositories, and [manage costs](https://buf.build/docs/subscription/manage-costs/) for
  the statement that public-repository types are not billable.
- [bufbuild/plugins](https://github.com/bufbuild/plugins) — the definitions behind every
  remote plugin, and the source for the stage 0 table.
- [protobuf-javascript](https://github.com/protocolbuffers/protobuf-javascript) — not
  archived, contrary to this entry's first draft.
- [ts-protoc-gen](https://github.com/improbable-eng/ts-protoc-gen) — the one generator
  with no remote plugin.
- Prior entry:
  [2026-08-02-validation-performance/](../2026-08-02-validation-performance/README.md) —
  where the validation rules live and why a rewrite in another language is not the answer.
