# What redeploying ord-app's main would ship

- **Date:** 2026-10-04
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; local verification in progress
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

**The crash is not explained by ord-app's code.** The crashed image was built from
`b95551f` as well, plus untracked files the app never imports. Redeploying `main`
does not by itself avoid whatever caused it.

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
- No AWS credentials were available, so the ECS service's running task definition was
  not read directly.

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

| # | check | why |
| --- | --- | --- |
| 1 | Existing prod reactions and datasets open, edit, save, and validate | Reactions are stored as serialized protos (`binpb`); the schema moved 0.3 → 0.6 |
| 2 | Dataset upload and download in every existing format, and Parquet | ord-schema and python-multipart upgrades; new pyarrow path |
| 3 | Paginated lists: datasets, reactions, groups, members | fastapi-pagination 0.12 → 0.15 |
| 4 | Structure drawing, SMILES and molblock round trips, image copy | Ketcher 3.8 → 3.15 |
| 5 | Login, and API calls going to the site's own origin | #734 |
| 6 | An unauthenticated API request is refused | the bypass in #667/#668 must stay off in prod |
| 7 | Access, role, and attachment-cap behavior with real accounts | #779, #783, #782, #610, #770, #771 |
| 8 | Spot-check the UI fixes | §3 |

Local results will be recorded here as they come in.

## Conclusions / next steps

- **Read the crashed tasks' logs before redeploying.** Section 2 narrows the crash to
  the infrastructure change or base-image drift; the logs should say which. If it was
  #41, a `main` redeploy will crash the same way.
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
