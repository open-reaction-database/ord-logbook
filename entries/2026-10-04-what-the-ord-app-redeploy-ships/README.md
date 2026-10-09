# What redeploying ord-app's main would ship

- **Date:** 2026-10-04
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** final; redeployed on 2026-10-09
- **Tags:** ord-app, deployment, pulumi, aws, dependencies, verification
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

app.open-reaction-database.org has not been rebuilt from ord-app's `main` since May.
An infrastructure deploy on 2026-10-04 rebuilt the image, the new tasks crashed, and
the service was rolled back by hand to an earlier image. Before `main` is redeployed:
which commit is prod actually serving, what has `main` changed since then, and what
should be checked before it ships?

## Summary

**Redeployed on 2026-10-09 (§6).** ord-app `main` at `b064d94` reached prod at 01:22
UTC, after Ben ran the signed-in checks in
[`assets/redeploy-checklist.md`](assets/redeploy-checklist.md) on a staging deploy
against prod's database. The interface stack's rebuild, for ord-interface#228, went out
the day before.

**Before that, prod served the image built on 2026-05-11 from ord-app
[`b95551f`](https://github.com/open-reaction-database/ord-app/commit/b95551ff697781c286c45317dd62c126caf6eacb)
(#649), with a local dependency fix (§2).** Pulumi's state did not say so: it recorded
the image that crashed, and the rollback happened outside Pulumi.

**`main` (`87ca9d5`, 2026-10-02) is 156 commits ahead.** 61 are test-only and about 30
are CI, lint, and tooling. What reaches users is 7 dependency upgrades — the large ones
are ord-schema 0.3 → 0.6, protobuf 4 → 5, FastAPI 0.115 → 0.138, Starlette 0.46 → 1.3,
and Ketcher 3.8 → 3.15 — about 40 UI and backend fixes, and Parquet dataset support.
**There are no new Alembic migrations**, so the redeploy needs no database step.

**The crashed image could not start.** It is a clean build of `b95551f`, where the
backend imports `httpx` at startup but `httpx` is only a development dependency, which
the image does not install: `ModuleNotFoundError: No module named 'httpx'`. The May
image runs because its build carried a local fix moving `httpx` and `psycopg` to
runtime dependencies, which #653 later merged. The crashed build also lacked the two
untracked files the build takes its Auth0 settings from, `ui/.env` and `ord_app/.env`,
so had it started it would have sent every visitor to `https://undefined/authorize`.
`main` has #653, and ord-app#841 and ord-infrastructure#47 have the app stack pass the
Auth0 settings as build arguments, failing the image build without them (§5.7).

**Local verification of `main` found two problems to fix before the redeploy, and one
already in prod:**

- Text-format (`.txtpb`) downloads of any dataset or reaction containing a non-ASCII
  character — `µ`, `°`, an en dash — return 500. This is a regression from protobuf 5.
  [ord-app#840](https://github.com/open-reaction-database/ord-app/pull/840), merged,
  fixes it.
- On the 4 GB task #41 introduced, a JSON or text download of a 50,688-reaction
  dataset is OOM-killed, and on 8 GB
  ([ord-infrastructure#46](https://github.com/open-reaction-database/ord-infrastructure/pull/46))
  it still outlasts nginx's 60 s timeout. The live version builds downloads the same
  way, so the cause is the downsizing, not `main`. ord-app#843, merged, streams
  downloads, and ord-infrastructure#51, merged, returns the task to 4 GB, where the same
  run peaks at 1.9 GiB (§5.10).
- Already in prod: a dataset whose name has a character outside Latin-1, such as an en
  dash, cannot be downloaded in any format. ord-app#840 fixes this too.

Everything else checked passes: stored reactions are wire-compatible and validate the
same, uploads in all five formats, exact download round trips, pagination, edit and
save, Ketcher, and the refusal of unauthenticated requests.

## Method

- **Pulumi.** `pulumi stack history` and `pulumi stack export` for `ord/prod` in
  ord-infrastructure's `stacks/app`, including `--version 50` and `--version 57` for the
  state before the 2026-10-04 update. The `docker-build:index:Image` resource records the
  `GIT_COMMIT` build argument that `Dockerfile.single` stamps into the image's
  `org.opencontainers.image.revision` label (ord-app#739).
- **The live site.** `curl` of `https://app.open-reaction-database.org/` and its main
  bundle, at 2026-10-05 01:06 UTC. nginx serves the built files with their build-time
  modification times.
- **git.** `git log --first-parent b95551f..origin/main` in ord-app, `git diff` of
  `migrations/`, `pyproject.toml`, `uv.lock`, `ui/package.json`, `ui/package-lock.json`,
  and `Dockerfile.single`, and the reflog of the ord-app checkout the deploy built from.
- **Local verification**, with the scripts in [`assets/`](assets/README.md):
  - ord-schema 0.3.100 and 0.6.31 side by side, on 10,548 reactions sampled from
    ord-data and on one mutated reaction per new validation rule;
  - `main` exported with `git archive`, run as the no-auth dev stack (Postgres from
    `docker-compose.yml`, uvicorn, Vite) and as the production image, built with
    `Dockerfile.single` for `linux/amd64` and run with prod's 2 CPUs and 4 GB;
  - uploads of three ord-data datasets (96, 1,536, and 50,688 reactions) in every
    format, downloads in every format, and a headless-Chromium pass over the UI.
- **Previews, 2026-10-07.** `pulumi preview --refresh` of every prod stack, from clones
  of ord-infrastructure, ord-app, and ord-interface at `main`, and the app service's
  task definitions read with `aws ecs`; the May and crashed images pulled from ECR and
  their files compared with `b95551f`.

## Findings

### 1. What prod is serving

| evidence | value |
| --- | --- |
| live `index.html` `Last-Modified` | Mon, 11 May 2026 03:00:38 GMT |
| live bundle | `/assets/index-Bz0MS1jK.js`; React 19.2.4 |
| Pulumi image built for prod updates 49 and 50 | 2026-05-11 03:03 UTC, digest `sha256:b293a614…` |
| last commit on ord-app `main` before that build | `b95551f`, 2026-04-18 |
| next commit on ord-app `main` | `7e5c709` (#652), 2026-05-12 |

The May build predates the revision label, so its commit is inferred: `main` sat at
`b95551f` from 2026-04-18 to 2026-05-12, and the bundle's React 19.2.4 entered the
lockfile with #647 (2026-02-17), so the build is no older than that. Its files are
`b95551f` plus a local change (§2). The rollback restored this image.

### 2. What the crashed deploy built

ord-infrastructure
[#41](https://github.com/open-reaction-database/ord-infrastructure/pull/41) (`a8df2cc`)
right-sizes the Fargate tasks and moves the shared cache from Redis OSS to Valkey. It
reached prod as two updates: the backend stack, which holds the cache, and then the app
stack. The app stack's update 58 cut ord-app's task from 4 vCPU / 8 GB to 2 vCPU / 4 GB
and rebuilt the image. It ran with `PULUMI_ALLOW_DIRTY` set, which skips the check that
the ord-app checkout is a clean, current `main`.

| time (UTC, 2026-10-05) | event |
| --- | --- |
| 00:04:47 | backend stack update 53 (#41: Valkey) starts |
| 00:24:43 | the ord-app checkout moves from `main` to `b95551f` |
| 00:26:19 | app stack update 58 (#41) starts |
| 00:29:54 | image built: `GIT_COMMIT=b95551f…-dirty`, digest `sha256:574566a7…` |
| 00:33:53 | new task definition registered: 2048 CPU units, 4096 MB |
| 00:37:09 | task definition `service-29ca0ae4:2` registered by hand, at the same size, with the May image (`sha256:b293a614…`); the service moves to it |
| 00:40:46 | the checkout moves back to `main` |
| 01:05:08 | backend stack update 54 ([#42](https://github.com/open-reaction-database/ord-infrastructure/pull/42): one load balancer for both sites, NAT-instance egress) starts |
| 01:06:10 | the live site answers with the May build |

The crashed image's files match `b95551f` exactly. The checkout's reflog records a stash
(`reset: moving to HEAD`) at 00:24:43, just before the move to `b95551f`, and the
uncommitted work it held, now
[ord-app#847](https://github.com/open-reaction-database/ord-app/pull/847), reappeared
when the checkout moved back, so the build saw none of it. What marked the tree
`-dirty` is not recorded.

The May image's files are not `b95551f`'s:

| | May image (`sha256:b293a614…`) | crashed image (`sha256:574566a7…`) |
| --- | --- | --- |
| application files | `b95551f`, except as below | `b95551f` |
| `pyproject.toml`, `uv.lock` | `httpx` and `psycopg` moved from the `dev` group to runtime dependencies | both only in `dev` |
| `import httpx` | 0.28.1 | `ModuleNotFoundError` |
| `ord_app/.env` | the five `VITE_AUTH0_*` settings | absent |
| also | stale `.pytype` caches in `ord_app/api/` and `ord_app/visualization/`, directories git dropped in #332 | — |

**That is the crash.** `Dockerfile.single` installs with `uv sync --frozen --no-dev`,
and at `b95551f` the backend imports `httpx` (`domain/users.py`,
`services/resolvers.py`) while `uv.lock` reaches it only through the `dev` group, so a
clean build of `b95551f` cannot start. The May build carried the local fix that #653
later merged.

The other differences from the May build, none needed to explain the crash:

- the Auth0 settings. The checkout had no `ui/.env` or `ord_app/.env`; both are
  gitignored. Vite compiles `VITE_AUTH0_*` from `ui/.env` into the bundle, and the
  backend reads `ord_app/.env`, since the task supplies only the database variables.
  The May bundle names the tenant's domain and client ID; a build without the files
  has `undefined` in their place (§5.4);
- the task size: half the CPU and memory, against the 1.9 GB peak #41 measured;
- the base images, which `Dockerfile.single` takes from floating tags
  (`node:22-alpine`, `python:3.12-slim`), and `uv`, installed unpinned with `pip`;
- the backend stack's changes from #41, applied 20 minutes before. ord-app's task
  receives only `PG_DSN` and `PGPASSWORD`, so it does not use the cache.

The rollback is `:2`, three minutes after the crashed `:1`; Pulumi's state recorded
`:1` until a refresh of the service on 2026-10-08.

### 3. What `main` changes

#### Dependencies (locked versions)

| package | prod (`b95551f`) | `main` | PR |
| --- | --- | --- | --- |
| ord-schema (Python) | 0.3.100 | 0.6.31 | #798, #806 |
| ord-schema-protobufjs (UI) | ^0.3.96 | ^0.6.31 | #798 |
| protobuf (Python) | 4.25.9 | 5.29.6 | #806 |
| fastapi | 0.115.14 | 0.138.0 | #804 |
| starlette | 0.46.2 | 1.3.1 | #804 |
| fastapi-pagination | 0.12.34 | 0.15.15 | #803 |
| python-multipart | 0.0.20 | ≥ 0.0.31 | #803 |
| pyarrow | — | 24.0.0 | #808 |
| ketcher-react / ketcher-standalone | 3.8.0 | 3.15.0 | #805 |
| npm packages in `ui/` | — | 63 security alerts resolved | #802 |

`httpx` and `psycopg` moved from development to runtime dependencies (#653).

#### Backend behavior

- A dataset or reaction the user cannot access returns 404 rather than 403 (#779).
- The single-group endpoint includes the caller's role (#783).
- A reaction's file attachments are capped at 10 MB in total (#782).
- Datasets read and write Parquet (#808).
- A no-auth bypass for local development and E2E (#667, #668). The backend enables it
  only when `ORD_APP_E2E` is set and `APP_ENV` is `localhost`; the UI only in a
  non-production build with `VITE_E2E_NO_AUTH=TRUE`.

#### Build

- The UI's API base defaults to the same-origin path `/api/v1` (#734), where it was
  read from whatever `ui/.env` the build machine had.
- The image is stamped with its source commit (#739).

#### UI behavior

- Request failures: a 403 re-checks the user's permissions and notifies (#770); an edit
  the backend rejects is rolled back (#771); the datasets list refetches on return, so
  deleted or no-longer-shared datasets drop out (#584).
- Permissions in the UI: removing a dataset is limited to admins (#610).
- New: Save and Close and Cmd/Ctrl+Enter in reaction sidebars (#812); templates show
  their last-modified time in the user's time zone (#619).
- Fixes, about 30: the limiting-reactant badge (#487), SI units and readable amounts
  (#436), conversion and yield in the outcome preview (#598), outcomes ordered by time
  (#599), the electrochemistry voltage field (#623), pagination after deleting a page's
  last reaction (#586), wide reactions scroll instead of clipping (#408), 404 for an
  unknown template (#496), invalid enumeration dates rejected (#544), "Show Invalid
  Only" per dataset (#591), a loader while reactions validate (#622) and while a
  reaction loads (#312), full-height reaction image copies (#587), Paste Chunk
  submitting filtered values (#601, #592), and character-limit and truncation fixes
  (#511, #612, #355, #356, #609).

### 4. What to verify before the redeploy

| # | check | why | local result |
| --- | --- | --- | --- |
| 1 | Existing prod reactions and datasets open, edit, save, and validate | Reactions are stored as serialized protos (`binpb`); the schema moved 0.3 → 0.6 | pass on ord-data reactions (§5.1); prod's own data not tried |
| 2 | Dataset upload and download in every existing format, and Parquet | ord-schema and python-multipart upgrades; new pyarrow path | on `main`, pass: `.txtpb` with non-ASCII text, non-Latin-1 dataset names, and every format of the 50,688-reaction dataset, streamed, at 4 GB (§5.5, §5.9, §5.10) |
| 3 | Paginated lists: datasets, reactions, groups, members | fastapi-pagination 0.12 → 0.15 | pass for datasets and reactions |
| 4 | Structure drawing, SMILES and molblock round trips, image copy | Ketcher 3.8 → 3.15 | Ketcher 3.15 opens; drawing and image copy not tried |
| 5 | Login, and API calls going to the site's own origin | #734 | on `main`, pass up to Auth0's sign-in page, from build arguments alone (§5.9) |
| 6 | An unauthenticated API request is refused | the bypass in #667/#668 must stay off in prod | pass, on `main` too (§5.4, §5.9) |
| 7 | Access, role, and attachment-cap behavior with real accounts | #779, #783, #782, #610, #770, #771 | not run locally; `main`'s CI covers the backend side |
| 8 | Spot-check the UI fixes | §3 | the badges, units, outcome time, size pill, and Save and Close render and work |

### 5. What local verification found

#### 5.1 Stored reactions read and validate the same

The 292 fields and every enum value reachable from `Reaction` and `Dataset` have the
same numbers, types, and labels in ord-schema 0.3.100 and 0.6.31, so `binpb` written by
prod parses unchanged. Validated as ord-app validates them, none of 10,548 ord-data
reactions changed between valid and invalid. 0.6.31 adds warnings: a `STIRRING` workup
without a stirring definition (966 reactions) and a reaction SMILES with atom maps but
no `is_mapped` (300).

ord-data is curated, so it would not show a new rule that rejects what users enter. One
mutated reaction per rule from ord-schema #817 shows which rules reject: of 13
mutations, only two turn a reaction 0.3.100 accepts into an invalid one — an ORCID
with a bad check digit, and a TIC `tic_minimum_mz` above `tic_maximum_mz`. ord-app
fills the record creator's ORCID from ORCID sign-in (`domain/reactions.py`), which
should pass; ORCIDs typed into provenance by hand are the exposure.

#### 5.2 Text-format downloads fail on non-ASCII text

`write_message` in `services/pb_utils.py` calls `text_format.MessageToBytes(message)`.
protobuf 4.25.9 escaped non-ASCII characters as octal; 5.29.6 writes them as UTF-8 and
then encodes as ASCII, which raises `UnicodeEncodeError`. Both the dataset and the
single-reaction `.txtpb` downloads go through it, and reaction text routinely holds
`µ`, `°`, or `–`: the 96-reaction ord-data dataset fails and the 1,536-reaction one,
pure ASCII, passes. In the UI, choosing `.txtpb` from **Download Reaction** does nothing:
no file, no error. Passing `as_utf8=True` restores the download.

#### 5.3 Large downloads exceed the 4 GB task

The production image runs three uvicorn workers. Uploading the 50,688-reaction dataset
twice (as `.pb.gz` and as `.parquet`, 7–9 s each) succeeded, and background validation
of the 101,376 reactions began. Downloads of it as JSON and as text then ran into the
4 GB limit: Docker recorded an OOM kill, two of the three workers died, and nginx
returned 504 after 60 s.

Serializing that dataset in one process, with nothing else running:

| serialization | protobuf 4.25.9 (prod) | protobuf 5.29.6 (`main`) | output |
| --- | --- | --- | --- |
| parse only | 0.9 GB | 0.9 GB | — |
| `binpb` | 1.4 GB | 1.5 GB | 172 MB |
| JSON | 4.5 GB | 5.2 GB | 911 MB |
| text | 4.1 GB | 4.1 GB | 641 MB |

JSON and text downloads build the whole document in memory, so a dataset of this size
does not fit in 4 GB under either version. 8 GB does not fix it either (§5.9);
streaming does (§5.10).

#### 5.4 The production image and sign-in

Built from a clean export of `main`, the image starts, answers the load balancer's
health check (`/api/v1/canonicalize-smiles?smiles=C`), and idles at about 600 MB.
Unauthenticated API requests get 401, and the E2E dev token gets 403 — the bypass is
off unless `APP_ENV` is `localhost` and `ORD_APP_E2E` is set.

Without `ui/.env`, the bundle's Auth0 domain, client ID, audience, issuer, and scope
are `undefined`, and the browser is sent to `https://undefined/authorize`, which fails
to resolve. With the files, it is sent to the tenant's `/authorize` with the client ID
and the `openid profile email offline_access` scope. Sign-in was not completed, since
Auth0 accepts only the registered callback URLs.

#### 5.5 Uploads, downloads, and the UI

| dataset | reactions | uploads (`.pb`, `.pb.gz`, `.pbtxt`, `.json`, `.parquet`) | downloads |
| --- | --- | --- | --- |
| Reizman Suzuki (non-ASCII text) | 96 | all 200; count and pages match | `binpb`, JSON, Parquet pass; `.txtpb` 500 |
| HTE Pd cross-coupling | 1,536 | all 200; count and pages match | all four pass |
| Cernak C–N coupling | 50,688 | `.pb.gz`, `.parquet` 200 | all fail: name header (below), memory (§5.3) |

Every successful download parses back to the uploaded reactions exactly; only
`dataset_id` differs, which the app assigns.

The 50,688-reaction dataset's `binpb` and Parquet downloads fail for a reason prod
shares: the response names the file `"{dataset.name}.{format}"` in a
`Content-Disposition` header, and Starlette encodes headers as Latin-1, so an en dash in
the name raises `UnicodeEncodeError`. Starlette 0.46.2 and 1.3.1 both raise, and the
header code is unchanged since `b95551f`.

In the UI, the datasets list shows the size pills, a reaction shows the
limiting-reactant badge, units, and outcome time, an amount edited and saved with
**Save and Close** survives a reload, and Ketcher 3.15 opens from **Add Molblock
Identifier**. The E2E suite, one smoke test, passes. `main`'s CI is green at
`87ca9d5`.

#### 5.6 The fixes, tested

[ord-app#840](https://github.com/open-reaction-database/ord-app/pull/840), merged, fixes
both download failures:

- `write_message` serializes text format with `as_utf8=True`.
- Downloads name the file as RFC 6266 describes: an ASCII `filename` fallback, with
  `"`, `\`, and anything outside printable ASCII replaced by `_`, and the exact name,
  percent-encoded as UTF-8, in `filename*`. The UI read the name with
  `/^.*filename="(.*)"/`, which would have kept the trailing `filename*` parameter in
  the saved name, so it reads `filename*` first and falls back to `filename`.

| test | result |
| --- | --- |
| New tests: a non-ASCII reaction round-trips through `binpb`, JSON, and text; a dataset named `C–N coupling at 25 °C` downloads in all four formats; a reaction's `.txtpb` download with non-ASCII text; the header fallbacks; the UI's header parser | pass |
| ord-app's backend suite (`pytest -n auto`), `ruff`, `ruff format`, `ty` | 104 passed; clean |
| The download thunk's `vitest` file, `tsc -b`, `eslint`, `prettier` | 7 passed; clean |
| Local stack: the 96-reaction dataset's `.txtpb` download, and one of its reactions' | 500 before, 200 after |
| Local stack: the 1,536-reaction dataset renamed `C–N coupling at 25 °C`, downloaded from the UI | saved under that exact name in all four formats |
| Local stack: the non-ASCII reaction downloaded from the UI | `.binpb`, `.txtpb`, and `.json` all saved |
| #840's CI: Python on Ubuntu and macOS, UI, E2E, lint and build, duplication, license headers, SonarCloud | all pass; Greptile 5/5 |

[ord-infrastructure#46](https://github.com/open-reaction-database/ord-infrastructure/pull/46)
sets ord-app's prod task to 2 vCPU / 8 GB, a valid Fargate pairing, at about $13 a
month more. Its `ruff`, `ty`, and `pytest` (13 passed) are clean; `pulumi preview` was
not run, since it builds the ord-app image from the sibling checkout. It has merged;
ord-infrastructure#51 has since returned the task to 4 GB (§5.10).

#### 5.7 The Auth0 settings, from the stack

An image build no longer depends on `.env` files in the deploy checkout:

- [ord-app#841](https://github.com/open-reaction-database/ord-app/pull/841), merged:
  `Dockerfile.single` takes `VITE_AUTH0_DOMAIN`, `_CLIENT_ID`, `_AUDIENCE`, `_ISSUER`,
  and `_SCOPE` as build arguments, which take precedence over `ui/.env`. An argument not
  passed stays unset, so `ui/.env` still works. The image build sets
  `ORD_APP_REQUIRE_AUTH0`, and `vite.config.ts` then fails the build, naming any
  missing setting; other builds are unaffected.
- [ord-infrastructure#47](https://github.com/open-reaction-database/ord-infrastructure/pull/47),
  merged: the app stack passes the settings as build arguments, and as task environment
  for the backend's token checks. The tenant domain and the ORD App client ID come from
  the `auth` stack, which owns that client.
- [ord-infrastructure#49](https://github.com/open-reaction-database/ord-infrastructure/pull/49),
  merged:
  the app stack reads those two outputs with `require_output`. With `get_output`, an
  `auth` stack not yet redeployed with its new `domain` output gave the issuer as
  `https://None/` and dropped the domain build argument. The change first reached
  `main` without review and was reverted in #48.

| test | result |
| --- | --- |
| `vite build` with the check on: no settings; only the domain; `ui/.env`; environment only | fails naming all five; fails naming the other four; passes; passes |
| `vite build` with the check off | builds as before |
| `docker build --target react-build`: no arguments or `ui/.env`; arguments and a conflicting `ui/.env` | fails with the message; the bundle holds the argument's domain |
| #841's CI: a step requiring an image-style build to fail without the settings, and the regular build with the check on and placeholder values | pass, SonarCloud included; the step fails when the check is disabled; Greptile 5/5 |
| ord-infrastructure, under Pulumi mocks: `make_web_service` and the app stack program | 17 pass; they fail when a caller's `GIT_COMMIT` wins, `build_args` is dropped, the scope is left out, or `get_output` replaces `require_output` |

#### 5.8 Also in the redeploy

- [ord-app#839](https://github.com/open-reaction-database/ord-app/pull/839), merged:
  nginx compresses the UI bundles, the API's JSON, and downloads, at level 6. Downloads
  needed a content type for nginx to compress them, so each format has one. At level 6
  the 12.7 MB UI bundle sends 4.3 MB, and the 50,688-reaction dataset sends 5.0 MB as
  binpb (from 181 MB), 19.5 MB as JSON (from 956 MB), and 11.3 MB as text (from
  673 MB); Parquet, already compressed, is left alone. Level 6 is where zlib's ratio on
  JSON levels off: 41× at 5, 55× at 6, and 63× at 8 at half the speed.
- [ord-app#842](https://github.com/open-reaction-database/ord-app/pull/842), merged:
  resolves the 81 Dependabot alerts open on `main`, four of them critical (PyJWT,
  anyio, and tinypool twice). It takes Vitest 3 → 4 and csv-parse 5 → 7, with a new
  test of CSV upload that passes on both csv-parse versions. Vitest 4 counts branches
  differently (61% of 1,487 where Vitest 3 counted 84% of 1,623 for the same tests),
  so the branch-coverage floor moves from 80% to 57%.
- [ord-interface#228](https://github.com/open-reaction-database/ord-interface/pull/228),
  merged: ord-interface's nginx had `gzip on` but no `gzip_types`, so it compressed
  only `text/html`. It now compresses its bundles and JSON the same way.

#### 5.9 `main` after the fixes

The production image built from a clean export of `main` (`7858249`, with #839–#842)
the way the app stack now builds it: the five Auth0 settings as build arguments and no
`.env` files. It ran at #46's 2 vCPU / 8 GB, under amd64 emulation.

| check | result |
| --- | --- |
| The bundle and sign-in | names the tenant and client ID, calls `/api/v1`; the browser goes to the tenant's `/authorize` with the client ID, scope, and audience |
| An unauthenticated request; the E2E dev token without the bypass | 401; 403 |
| `.txtpb` of the 96-reaction dataset, and of one of its reactions | 200 |
| The 50,688-reaction dataset, named with an en dash: `binpb`, Parquet | 200, saved under the exact name; `binpb` gzipped |
| The same dataset as JSON, then as text, with nothing else running | 504 after nginx's 60 s timeout; the text download, overlapping the abandoned JSON one, took memory to 8 GB and was OOM-killed |
| The same downloads while 101,376 new reactions validate in the background | the same: 504, then an OOM kill |

JSON and text downloads build the whole document before sending a byte. Serializing
this dataset takes 31.8 s as JSON and 19.9 s as text natively on an M5 Pro, before the
database reads, and the emulated image did not finish the JSON within 60 s. Fargate's
x86 vCPUs are slower per core than an M5 Pro, so a download this size likely times out
in prod as well. nginx gives up at 60 s, but the backend keeps serializing, so the abandoned
request holds its ~5 GB while the next one starts. Prod's May image has the same
timeout and serializes the same way, so this is not new in `main`.

#### 5.10 Streamed downloads, and links the browser fetches

- [ord-app#843](https://github.com/open-reaction-database/ord-app/pull/843), merged:
  downloads stream. The backend reads a dataset's stored reactions through one database
  cursor, 1,000 at a time, so every batch comes from the same snapshot, and sends each
  batch as it is serialized: binpb copies the stored bytes with no parsing, JSON and
  text write one reaction at a time, and Parquet writes row groups to a staged file
  through ord-schema's `DatasetWriter`, then sends it. For a dataset with reactions,
  streamed binpb, JSON, and text are byte-identical to the whole-file output.
- [ord-app#845](https://github.com/open-reaction-database/ord-app/pull/845), merged: the
  UI downloads a dataset by asking the backend for a link and letting the browser fetch
  it, so the file streams to disk and appears in the browser's downloads list with its
  progress, rather than collecting in the page first. The link's token names the
  dataset, format, and user, expires after 30 s, and is signed with HMAC-SHA256;
  fetching it checks the user's access again. The backend does not start without
  `DOWNLOAD_LINK_SECRET` unless `APP_ENV` is `localhost`. Reaction downloads are
  unchanged.
- [ord-infrastructure#50](https://github.com/open-reaction-database/ord-infrastructure/pull/50),
  merged: the app stack generates that key per environment, stores it in Secrets
  Manager, and injects it into the task, which starts only once the key has a value.
- [ord-infrastructure#51](https://github.com/open-reaction-database/ord-infrastructure/pull/51),
  merged: ord-app's task returns to 2 vCPU / 4 GB, the least memory Fargate pairs with
  2 vCPU.

The production image built from ord-app `main` at `9a058db` (#845), run at 2 vCPU /
4 GB under amd64 emulation, through nginx, twice, the second time with
`assets/check_image.sh`. Timings vary with how much validation is running: the second
run also validated the first run's reactions.

| check | result |
| --- | --- |
| idle | 635 MiB |
| upload the 50,688-reaction dataset as `.pb.gz` and as `.parquet`, and the 96-reaction one | all succeed; 101,376 reactions start validating |
| download the large dataset while they validate | 200 in every format: binpb 180 MB in 11–30 s, JSON 955 MB in 87–120 s, text 672 MB in 66–97 s, Parquet 5 MB in 3–12 s |
| peak memory | 1.88 GiB and 1.75 GiB; no OOM kill, no worker deaths |

Natively, with #843, every format's response headers arrive within 50 ms, and the
dataset takes 25.2 s as JSON, 21.3 s as text, 0.9 s as binpb, and 1.2 s as Parquet,
whose body starts once its staged file is complete. In Playwright's Chromium, Firefox,
and WebKit, the dataset menu's link saves the same bytes as the bearer download,
without leaving the page.

### 6. The redeploy

All times are UTC.

**Staging, 2026-10-08 12:48 to 2026-10-09 01:12.** The app stack's staging stack ran
ord-app `b2423d4` against prod's `app` database at prod's 2 vCPU / 4 GB
([ord-infrastructure#52](https://github.com/open-reaction-database/ord-infrastructure/pull/52)).
Its task had `PG_DSN` ending in `/app` and both secrets, its three workers started
cleanly, and its bundle named the Auth0 tenant. Ben ran the checklist there. One
`.parquet` download returned 422, for a dataset with no description, and the UI said
only "Unknown error";
[ord-app#848](https://github.com/open-reaction-database/ord-app/pull/848) shows the
backend's message for a 400, 409, or 422 and rewords three that had not been written
for users.

**Interface, 2026-10-08 01:18.** The interface stack rebuilt ord-interface at
`1953940`, with #228's compression. Its main bundle now transfers 202 KB gzipped
instead of 929 KB.

**App, 2026-10-09 01:22.** The app stack deployed ord-app `main` at `b064d94`, which
adds #848 to what staging ran, from ord-infrastructure `98d3958`. The update made 18 changes: the new task definition and image, the download
link key, and the move onto the shared load balancer, which deleted the app's own.

| check | result |
| --- | --- |
| ECS | one deployment, rollout complete, 1 task on `service-6163e898:1` |
| task | 2 vCPU / 4 GB; `PG_DSN` names `app`; `PGPASSWORD` and `DOWNLOAD_LINK_SECRET` |
| startup | all three workers report "Application startup complete"; no errors |
| site | health check 200, an unauthenticated request 401, `index.html` built at 01:23:42 |
| bundle | names the Auth0 tenant and client ID, calls `/api/v1`, served gzipped |
| load balancer | DNS points at the shared load balancer; the app's own is deleted |
| availability | 2 of 84 health checks, at 01:28:22 and 01:28:27, returned 503 during the cutover |

**Afterwards, 2026-10-09.**

- A refresh of all seven prod stacks changed only the `domain` and `database` stacks'
  copies of the backend stack's outputs.
- The `database` stack dropped `app_staging` (#52), and every database it manages is
  protected
  ([ord-infrastructure#54](https://github.com/open-reaction-database/ord-infrastructure/pull/54)).
- A sweep for AWS resources in no stack's state found nothing running or billing
  unexpectedly. It removed six RDS subnet groups for VPCs that no longer exist and 13
  ECR images: the crashed one, eleven older builds, and, once Ben signed off, the May
  image with its task definition `:2`. Each web service's repository now keeps its
  newest five images
  ([ord-infrastructure#53](https://github.com/open-reaction-database/ord-infrastructure/pull/53)).
  Two manual Aurora snapshots, from 2025-03-31 and 2026-06-14, were kept.

## Conclusions / next steps

- **The redeploy is done (§6).** `main` is in prod, the signed-in checks passed on
  staging against prod's data, and the crashed image, the rollback, and `app_staging`
  are gone. Rolling back now means redeploying an earlier commit.
- **The `backend` stack's bastion** would be replaced on its next deploy, because its
  AMI lookup finds a newer image; nothing else in that stack has drifted.
- **Pin the base images and `uv`** in `Dockerfile.single`, so a rebuild of an old
  commit reproduces the image that ran.
- **Deploy from a clean checkout.** The May image carries an uncommitted fix,
  `ord_app/.env`, and stale caches from its checkout, so no commit reproduces it, and
  update 58 built with `PULUMI_ALLOW_DIRTY`. With the gate on, an image is exactly a
  commit on `main`.

## References

- [ord-app `b95551f…87ca9d5`](https://github.com/open-reaction-database/ord-app/compare/b95551ff697781c286c45317dd62c126caf6eacb...87ca9d5)
  — everything the redeploy ships.
- [ord-infrastructure#41](https://github.com/open-reaction-database/ord-infrastructure/pull/41)
  — the infrastructure change in the crashed deploy.
- [ord-app#840](https://github.com/open-reaction-database/ord-app/pull/840) — the
  `.txtpb` and download-name fixes.
- [ord-infrastructure#46](https://github.com/open-reaction-database/ord-infrastructure/pull/46)
  — ord-app's task back to 8 GB, until #51.
- [ord-app#841](https://github.com/open-reaction-database/ord-app/pull/841) and
  [ord-infrastructure#47](https://github.com/open-reaction-database/ord-infrastructure/pull/47)
  — the Auth0 settings as image build arguments from the app stack, and the build check.
- [ord-infrastructure#49](https://github.com/open-reaction-database/ord-infrastructure/pull/49)
  — `require_output` for the auth stack's outputs.
- [ord-app#839](https://github.com/open-reaction-database/ord-app/pull/839) and
  [ord-interface#228](https://github.com/open-reaction-database/ord-interface/pull/228)
  — compression in nginx.
- [ord-app#842](https://github.com/open-reaction-database/ord-app/pull/842) — the
  Dependabot alerts.
- [ord-app#843](https://github.com/open-reaction-database/ord-app/pull/843) and
  [ord-app#845](https://github.com/open-reaction-database/ord-app/pull/845) — streamed
  downloads, and links the browser fetches.
- [ord-infrastructure#50](https://github.com/open-reaction-database/ord-infrastructure/pull/50)
  and [ord-infrastructure#51](https://github.com/open-reaction-database/ord-infrastructure/pull/51)
  — the download link key, and the task back to 4 GB.
- [ord-app#848](https://github.com/open-reaction-database/ord-app/pull/848) — the
  backend's message in error notifications.
- [ord-infrastructure#52](https://github.com/open-reaction-database/ord-infrastructure/pull/52),
  [#53](https://github.com/open-reaction-database/ord-infrastructure/pull/53), and
  [#54](https://github.com/open-reaction-database/ord-infrastructure/pull/54) — staging
  on prod's database and size without `app_staging`, the ECR lifecycle rule, and one
  list of protected databases.
- [ord-app#739](https://github.com/open-reaction-database/ord-app/pull/739) — the
  revision label that identified the crashed image.
- [ord-app#656](https://github.com/open-reaction-database/ord-app/issues/656) — the
  issue-triage plan, which records the May build date and the issues closed as
  stale-deployment artifacts.
