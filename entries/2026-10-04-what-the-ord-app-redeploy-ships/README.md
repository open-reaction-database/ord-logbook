# What redeploying ord-app's main would ship

- **Date:** 2026-10-04
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; local verification done, checks that need a signed-in account remain
- **Tags:** ord-app, deployment, pulumi, aws, dependencies, verification
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

app.open-reaction-database.org has not been rebuilt from ord-app's `main` since May.
An infrastructure deploy on 2026-10-04 rebuilt the image, the new tasks crashed, and
the service was rolled back by hand to an earlier image. Before `main` is redeployed:
which commit is prod actually serving, what has `main` changed since then, and what
should be checked before it ships?

## Summary

**Prod serves the image built on 2026-05-11 from ord-app
[`b95551f`](https://github.com/open-reaction-database/ord-app/commit/b95551ff697781c286c45317dd62c126caf6eacb)
(#649).** Pulumi's state does not say so: it records the image that crashed, and the
rollback happened outside Pulumi.

**`main` (`87ca9d5`, 2026-10-02) is 156 commits ahead.** 61 are test-only and about 30
are CI, lint, and tooling. What reaches users is 7 dependency upgrades — the large ones
are ord-schema 0.3 → 0.6, protobuf 4 → 5, FastAPI 0.115 → 0.138, Starlette 0.46 → 1.3,
and Ketcher 3.8 → 3.15 — about 40 UI and backend fixes, and Parquet dataset support.
**There are no new Alembic migrations**, so the redeploy needs no database step.

**The crashed image could not have served users, whatever else went wrong.** It was
built from `b95551f` as well, but from a checkout without the two untracked files
the build takes its Auth0 settings from, `ui/.env` and `ord_app/.env`. A build without
them sends every visitor to `https://undefined/authorize`. The tasks' logs would say
whether the containers also crashed.

**Local verification of `main` found two problems to fix before the redeploy, and one
already in prod:**

- Text-format (`.txtpb`) downloads of any dataset or reaction containing a non-ASCII
  character — `µ`, `°`, an en dash — return 500. This is a regression from protobuf 5.
- On the 4 GB task #41 introduced, a JSON or text download of a 50,688-reaction
  dataset is OOM-killed. The live version needs as much memory for the same download,
  so the cause is the downsizing, not `main`.
- Already in prod: a dataset whose name has a character outside Latin-1, such as an en
  dash, cannot be downloaded in any format.

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
- No AWS credentials were available, so the ECS service's running task definition and
  the crashed tasks' logs were not read.

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
lockfile with #647 (2026-02-17), so the build is no older than that. The rollback
restored this image.

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
| 00:40:46 | the checkout moves back to `main` |
| 01:05:08 | backend stack update 54 ([#42](https://github.com/open-reaction-database/ord-infrastructure/pull/42): one load balancer for both sites, NAT-instance egress) starts |
| 01:06:10 | the live site answers with the May build |

`-dirty` counts untracked files as well as modified ones. The checkout's untracked
files are new modules (`ord_app/service_api/services/structures.py` and its tests,
`ui/src/store/entities/reactions/reactionEntity/structureIdentifiers.ts`) that nothing
at `b95551f` imports, so the crashed image ran the same application code as the one
that works. What did differ:

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

When the rollback happened, and the crashed tasks' own logs, were not read for this
entry.

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
| 2 | Dataset upload and download in every existing format, and Parquet | ord-schema and python-multipart upgrades; new pyarrow path | **fail**: `.txtpb` on non-ASCII (§5.2), large downloads at 4 GB (§5.3); the rest pass (§5.5) |
| 3 | Paginated lists: datasets, reactions, groups, members | fastapi-pagination 0.12 → 0.15 | pass for datasets and reactions |
| 4 | Structure drawing, SMILES and molblock round trips, image copy | Ketcher 3.8 → 3.15 | Ketcher 3.15 opens; drawing and image copy not tried |
| 5 | Login, and API calls going to the site's own origin | #734 | pass up to Auth0's sign-in page, given the `.env` files (§5.4) |
| 6 | An unauthenticated API request is refused | the bypass in #667/#668 must stay off in prod | pass (§5.4) |
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
does not fit in 4 GB under either version. By these numbers one such download at a
time fits in the old 8 GB task; that was not tested.

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

## Conclusions / next steps

- **Restore the Auth0 settings before any rebuild.** The `.env` files from the machine
  that built the May image go in the checkout Pulumi builds from. Longer term, pass
  the values from ord-infrastructure's stack config as build arguments and task
  environment, and fail the build when they are empty, so a clean checkout builds a
  working image.
- **Fix `.txtpb` downloads before shipping `main`** (§5.2).
- **Decide the task's memory before large downloads are allowed.** Either return to
  8 GB or stream JSON and text downloads. Prod's largest datasets
  (`SELECT dataset_id, count(*) FROM reactions GROUP BY 1 ORDER BY 2 DESC LIMIT 10`)
  say how urgent this is.
- **Fix download file names** with an RFC 6266 `filename*` parameter. This is already
  broken in prod, so it need not block the redeploy.
- **Read the crashed tasks' logs.** Section 2 leaves the missing Auth0 settings, the
  task size, and base-image drift; the logs should say which one crashed the
  containers.
- **Signed-in checks for the redeploy:** rows 1, 4, 5, and 7 of §4, on prod's data
  and accounts.
- **Run `pulumi refresh` on `ord/prod` before the next `up`,** so Pulumi stops treating
  the crashed task definition as live.
- **Pin the base images and `uv`** in `Dockerfile.single`, so a rebuild of an old
  commit reproduces the image that ran.
- **Deploy from a clean checkout.** Update 58 built with `PULUMI_ALLOW_DIRTY`, which
  is how untracked files reached a prod image.

## References

- [ord-app `b95551f…87ca9d5`](https://github.com/open-reaction-database/ord-app/compare/b95551ff697781c286c45317dd62c126caf6eacb...87ca9d5)
  — everything the redeploy ships.
- [ord-infrastructure#41](https://github.com/open-reaction-database/ord-infrastructure/pull/41)
  — the infrastructure change in the crashed deploy.
- [ord-app#739](https://github.com/open-reaction-database/ord-app/pull/739) — the
  revision label that identified the crashed image.
- [ord-app#656](https://github.com/open-reaction-database/ord-app/issues/656) — the
  issue-triage plan, which records the May build date and the issues closed as
  stale-deployment artifacts.
