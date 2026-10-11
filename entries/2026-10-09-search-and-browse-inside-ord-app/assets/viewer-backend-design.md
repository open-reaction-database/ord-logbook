# The viewer's backend in ord-app

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; design agreed, not started
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Step 3 of [the entry](../README.md)'s plan. Paths are in ord-app at
[`0984286`](https://github.com/open-reaction-database/ord-app/commit/0984286),
ord-interface at
[`1953940`](https://github.com/open-reaction-database/ord-interface/commit/1953940),
ord-schema at
[`19cb755`](https://github.com/open-reaction-database/ord-schema/commit/19cb755), and
ord-infrastructure at `676a420`, unless they say otherwise.

## Goal

Serve everything the viewer needs — browse, dataset pages and their charts, structure,
SMARTS, reaction SMARTS, and yield search, reaction detail, downloads, and `/ask` — from
a Python package in ord-app, built on `ord_schema.search` and DuckDB over the source
Parquet, with no Postgres and no Valkey. When this step is done:

- ord-app's Python lives in `backend/`, as two uv projects: `backend/editor` (today's
  `ord_app`, renamed `ord_editor`) and `backend/viewer` (`ord_viewer`, new);
- `ord_viewer` answers every route below against a corpus directory, with its own tests
  and CI jobs;
- the editor behaves as it does today;
- no viewer image or deployment exists yet. Those are steps 4 and 5.

## Decisions

| Question | Decision | Rejected |
| --- | --- | --- |
| Who the API serves | The viewer only. ord-interface's endpoints go away at step 5. | Keeping ord-interface's contract for outside scripts; a versioned public API |
| What it runs on | `ord_schema.search` for search, DuckDB over the source Parquet for records ([2026-10-03](../../2026-10-03-source-parquet-instead-of-the-orm/README.md)) | Porting the cartridge-backed queries |
| Where the corpus comes from | ord-schema derives and publishes it; the viewer only reads it | Deriving or publishing corpora from ord-app |
| How the two backends coexist | Two uv projects under `backend/`, each with its own lockfile | One workspace after upgrading the editor's ord-schema; a second package in today's project |
| Names | `backend/viewer` and `ord_viewer`, paired with `frontend/apps/viewer` and `deploy/viewer` | `backend/search` and `ord_search` |
| Request shape | The search grammar's `Query`, for both the form and `/ask` | Form-shaped parameters compiled on the server |
| How molecules reach the browser | Molblocks, in the editor's `{binpb, molblocks}` shape | Server-drawn SVG and HTML |

### Why two lockfiles

The editor locks ord-schema 0.6.31 and RDKit 2024.9. The viewer needs ord-schema 0.9.1,
the first release with the dataset filter
([ord-schema#1092](https://github.com/open-reaction-database/ord-schema/pull/1092)), the
chirality flag ([#1091](https://github.com/open-reaction-database/ord-schema/pull/1091)),
reaction SMARTS ([#1093](https://github.com/open-reaction-database/ord-schema/pull/1093)),
and `Corpus.reactions()` and `datasets()`
([#1095](https://github.com/open-reaction-database/ord-schema/pull/1095)). And `Corpus`
opens only artifacts stamped with the serving process's exact
ord-schema and RDKit versions, so the viewer's pins are set by the corpus ord-schema
published, not by the viewer. In one environment, every republished corpus that needs a
new ord-schema would re-pin the editor, and no editor upgrade could land before a
matching corpus existed. Separate projects let each move on its own schedule. The two
share no Python: a shared package would need compatible pins, and the shared code lives
in `frontend/packages/ui`.

## Layout

```text
backend/
  editor/                 uv project: pyproject.toml, uv.lock, alembic.ini, migrations/,
                          .env.template, the compose image's Dockerfile and entrypoint
    ord_editor/           today's ord_app/; service_api/ and the rest unchanged inside
  viewer/                 uv project: pyproject.toml, uv.lock
    ord_viewer/
      main.py             the FastAPI app; its lifespan opens the corpus
      settings.py         pydantic-settings, ORD_VIEWER_* variables
      corpus.py           opening and holding the Corpus, and the resolver cache
      molblocks.py        {inputs, outcomes, workups} for one reaction
      routes/             datasets, reactions, search, ask, download, health
      conftest.py         the fixture corpus
      testdata/           small source datasets
frontend/                 unchanged: apps/editor, apps/viewer (step 4), packages/ui
deploy/
  editor/                 Dockerfile (from Dockerfile.single), Dockerfile.dockerignore,
                          nginx.conf, supervisord.conf, entrypoint.sh
  viewer/                 step 4
ruff.toml                 one config for both projects
docker-compose.yml  .pre-commit-config.yaml  .jscpd.json  Makefile  scripts/
```

- **No Python project at the root.** Pre-commit runs as `uvx pre-commit`, and each
  `ty` hook as `uv run --project backend/<name> ty check`. The root `ruff.toml` replaces
  `[tool.ruff]` in today's root `pyproject.toml` and sets `src` so isort knows each
  first-party package.
- **Tests sit beside the code** as `*_test.py`, as in `ord_app` today. Each project's
  pytest root is its own directory, so `ord_editor`'s Postgres fixtures never run for
  `ord_viewer`.
- **Each image has its own ignore file.** `Dockerfile.dockerignore` beside each
  Dockerfile overrides the root `.dockerignore`, so the viewer's image never copies
  `backend/editor`.
- **Removed:** `MANIFEST.in`, which grafts directories that no longer exist, and
  `.pylintrc`, which nothing runs.

### Pins

`ord_viewer` pins `ord-schema[search,nl]` and `rdkit` with `==` to the versions that
derived the published corpus, and installs ord-schema from a release only. Installed
from git, ord-schema reports its last release's version while running different code,
so the stamp check could not catch a mismatch. V1 starts on ord-schema 0.9.1, released
on 2026-10-11 with everything merged since v0.9.0, and RDKit 2026.3.5, the version
ord-schema locks at that release. Both follow the stamps of the corpus ord-schema
publishes.

## API

Routes are declared under `/api/` in the app and passed through by nginx, as the editor
does with `/api/v1/`. They carry no version: the viewer and its API ship in one image,
so they cannot drift apart, and no other client depends on them.

| Route | Request | Response | Replaces in ord-interface |
| --- | --- | --- | --- |
| `GET /api/datasets` | | `[{dataset_id, name, description, reactions}]` | `/datasets` |
| `GET /api/datasets/{dataset_id}` | | one, or 404 | `/dataset` |
| `GET /api/datasets/{dataset_id}/compounds` | `side=inputs\|products`, `limit` (default 30, at most 100) | `[{smiles, molblock, count}]` | `/input_stats`, `/product_stats` |
| `GET /api/reactions` | `id`, repeated, at most 100 | `[{reaction_id, dataset_id, binpb, molblocks}]` | `/reactions`, `/reaction_summary`, `/compound_svg` |
| `GET /api/reactions/{reaction_id}` | | one, or 404 | `/reaction` |
| `POST /api/search` | `{query}` | a result | `/query`, `/submit_query`, `/fetch_query_result` |
| `POST /api/ask` | `{question}`, 1 to 2,000 characters | `{query, text, result}` | `/nl_query` |
| `POST /api/download` | `{reaction_ids}`, at most 1,000 | a gzipped `ord.Dataset`, with `Content-Disposition` | `/download_search_results` |
| `GET /api/health` | | `{fingerprint}` | the load balancer's check on `/molfile` |

- **The request is the grammar.** The search form and `/ask` both produce a `Query`, so
  the viewer can show what a question compiled to and open it in the form. This exposes
  nothing `/ask` does not: a model can already emit any grammar query, and the grammar
  was built for that — no SQL, a row bound, a whole-call timeout, and a sandboxed DuckDB.
  FastAPI's OpenAPI document carries the `Query` JSON Schema.
- **A result** is `{kind: "reactions", reaction_ids, truncated}`, or
  `{kind: "table", columns, rows, truncated}` for an aggregate. `truncated` is the
  `ord.truncated` flag `Corpus.search` sets when the 1,000-row bound may have cut the
  answer. The viewer then fetches a page of cards at a time through `/api/reactions`.
- **A reaction** is the editor's response shape, less its editor fields: `binpb` is the
  base64 serialized `Reaction`, as `Corpus.reactions()` returns it, and `molblocks` is
  `{inputs, outcomes, workups}`, built with `message_helpers.molblock_from_compound`.
  The shared package's `ordBinpbToReaction` and `getReactionPreviews` already read both,
  and Indigo draws them in the browser. IDs come back in the order asked, and unknown
  IDs are skipped.
- **The batch fetch is a GET**, to match datasets: 100 IDs are about 4 KiB of query
  string, inside nginx's default 8 KiB request line, and the pages can be cached. Search,
  ask, and download take bodies; 1,000 IDs are about 40 KiB.
- **Dataset compounds** are an aggregate over `inputs.components` or
  `outcomes.products`, filtered by `dataset_id` and grouped by `smiles`, each row with a
  molblock for the chart's image. They ran in 0.04–0.93 s in
  [2026-10-03](../../2026-10-03-source-parquet-instead-of-the-orm/README.md#5-every-other-postgres-read-has-a-route).
- **Datasets** come from `Corpus.datasets()`, sorted by name. `submitted_at` waits on the
  [date decisions](../../2026-09-03-date-time-formats/README.md).
- **Downloads** are `.pb.gz` only, as in ord-interface's UI, built in memory: a
  1,000-reaction download is about 3 MiB.

### Errors

| Raised | Status |
| --- | --- |
| `query.QueryError`, or a compound that does not resolve | 422, with the message |
| `TimeoutError` from `Corpus.search` | 504 |
| No free search slot within 10 s | 503 |
| `/ask` with no API key, or `ModelUnavailableError` | 503 |
| `ModelRateLimitedError` | 429 |
| `ModelRefusedError`, `UnanswerableError` | 422, with the model's reason |
| `MalformedQueryError` | 502 |

### Dropped

- `/molfile`. Ketcher 3 loads SMILES directly, and the health check has its own route.
- Valkey and the submit-and-poll pair. They exist because cartridge searches were slow;
  a search now takes at most 1.4 s on its first ask, under a timeout.
- `/reaction_summary`'s HTML and `/compound_svg`'s server-drawn SVG.
- `dry_run` on `/ask`.

## Runtime

- **One process, one corpus.** `uvicorn ord_viewer.main:app` with one worker, since a
  corpus over ORD holds about 7 GiB with an occurrences directory. Handlers are plain
  `def`, so FastAPI runs them on its threadpool; `Corpus` is safe to share across
  threads. A semaphore caps searches and asks in flight at `MAX_CONCURRENT`; a request
  that waits 10 s for a slot gets 503. Each search gets cores ÷ `MAX_CONCURRENT` RDKit
  threads.
- **Opening.** The lifespan opens the corpus with `require_current`, `require_pivots`,
  and `require_occurrences`, `warm=True`, `sources_pattern`, and `max_rows=1000`, then
  calls `check_pivots()`, which takes the first-ask cost off every pivot level. That is
  about 40 s, during which uvicorn accepts no connections. A stale or mismatched corpus
  raises, and the process exits non-zero rather than serve. A new corpus is a new
  deployment; swapping in place would double memory.
- **Compound names.** A `{"compound": ...}` value resolves through ord-schema's chain —
  PubChem, CACTUS, then OPSIN — behind an in-process LRU passed as `Corpus(resolver=...)`,
  in place of ord-interface's 30-day Valkey cache.
- **`/ask`** calls `nl.ask(question, corpus, timeout_seconds=60)`: one model call to
  translate and one to write the answer's sentence, with the system prompt cached by
  ord-schema. The concurrency cap covers it, and the viewer image's nginx adds a
  per-client `limit_req` on `/api/ask` (step 4).
- **No CORS middleware.** nginx serves the API and the SPA from one origin, and Vite
  proxies `/api` in development.

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `ORD_VIEWER_CORPUS_DIR` | required | A root holding `projections/`, `structures/`, `pivots/`, `occurrences/`, and `sources/`: the layout ord-schema publishes, and its derive scripts' until then |
| `ORD_VIEWER_MEMORY_LIMIT` | unset | DuckDB's `memory_limit` |
| `ORD_VIEWER_MAX_CONCURRENT` | 4 | Searches and asks in flight |
| `ORD_VIEWER_SEARCH_TIMEOUT_SECONDS` | 30 | Passed to `Corpus.search` |
| `ORD_VIEWER_ASK_MODEL` | ord-schema's `DEFAULT_MODEL` | The model `/ask` uses |
| `ORD_VIEWER_ASK_LOG` | `none` | `none` or `stdout`: the question log's sink |
| `ORD_ANTHROPIC_API_KEY` | unset | ord-schema's own variable, falling back to `ANTHROPIC_API_KEY`; without either, `/api/ask` returns 503 and the rest works |

## Testing

- **A fixture corpus, derived rather than committed.** A session fixture derives a
  corpus into a temporary directory from two or three small source datasets in
  `ord_viewer/testdata/`, with ord-schema's derive scripts run in the test environment,
  so the stamps match by construction. A committed corpus would go stale with every pin.
  The datasets are chosen to exercise a stereocenter, a reaction SMARTS, yields, two
  datasets for the dataset filter, and a name the offline resolver knows.
- **Routes through `TestClient`**, with the lifespan pointed at the fixture corpus: each
  route, its limits, and every row of the error table, including 503 when the semaphore
  is full.
- **No network.** `/ask` gets a fake Anthropic client through a dependency the tests
  override, and the corpus gets an offline resolver.
- **The response shape** is asserted in Python. Step 4 records a real response for the
  viewer's own tests.
- **CI.** A new job, `test_python_viewer`, on Ubuntu and macOS, runs `uv sync --frozen`
  and `pytest -n auto` in `backend/viewer`, with no Postgres. Its `fail_under` floor
  starts at the coverage the first PR measures, and at least the editor's 80.
  `check_python` gains the viewer's ruff and `ty` steps and keeps its name.
- **The full corpus stays out of CI.** Each search PR records the canonical requests'
  timings against a full local corpus, and step 5 runs `ord_schema.search.check` against
  the published one.

## Migration

Outside ord-app, first:

- ord-schema 0.9.1, which V1 pins, released on 2026-10-11;
- a corpus derived and published by that release, which step 5 needs and step 3 does
  not.

In ord-app, each PR from an up-to-date `main`, green on its own:

| PR | Change |
| --- | --- |
| L1 | `git mv` the Python, its lockfile, the migrations, and the compose image into `backend/editor/`, rename `ord_app` to `ord_editor`, and update every path that names them: `Dockerfile.single` and `supervisord.conf` in place, CI working directories, pre-commit, compose, Dependabot's docker directories, the Makefile, `scripts/`, `.jscpd.json`, the docs and `.claude/` guides, and the one frontend comment |
| L2 | Move the image's files into `deploy/editor/`, and point Dependabot's docker entry at them. A paired ord-infrastructure PR changes `stacks/app`'s `dockerfile` to `../../../ord-app/deploy/editor/Dockerfile` and merges before the next deploy |
| V1 | `backend/viewer`: the project, its lockfile, settings, the lifespan, `/api/health`, the fixture corpus, CI, hooks, and docs |
| V2 | Datasets, reactions with molblocks, and downloads |
| V3 | Search, the error table, the concurrency cap, and the resolver cache |
| V4 | `/ask` |

They run in that order, since V1 builds on L1's root `ruff.toml` and hooks, and nothing
outside ord-app blocks them now that 0.9.1 is out. CI job names stay
`test_python`, `check_python`, and `test_e2e`; `test_python_viewer` is new and has to be
added to the branch protection's required checks by hand.

## Risks

- **L1 touches every backend file.** Land or rebase open backend PRs first, as with the
  frontend's W1.
- **The pins and the corpus move together.** A new ord-schema pin needs a corpus derived
  by that version, and the service refuses to start until one exists. That is intended,
  but it orders every bump.
- **Answers change at the switch.** Chirality is matched by default; a multi-template
  reaction SMARTS returns fewer reactions than `@>`
  ([2026-10-02](../../2026-10-02-reaction-smarts-without-the-cartridge/README.md)); the
  dataset charts use the projection's SMILES. The viewer should say so (step 4); this
  step changes none of it.
- **jscpd may match `molblocks.py` against the editor's `get_molblocks`.** They are
  written against different ord-schema versions and expected to diverge.

## Step 5 inherits

- **Sizing.** About 4 vCPU and 16 GB, against ord-interface's 1 vCPU and 2 GB: the
  search README plans about 8 GiB resident, 7 with an occurrences directory, and DuckDB's
  caches fill whatever `memory_limit` allows.
- **The corpus in the container**, from wherever ord-schema publishes it.
- **The interface stack's contract:** the new Dockerfile path, port, health check path,
  and `ORD_VIEWER_*` settings in place of `POSTGRES_*` and `VALKEY_*`.
- **Retiring Valkey and the `ord_*` Aurora databases**, which have no other reader.

## Not in this step

The viewer's frontend and image (step 4); deployment, sizing, and getting the corpus to
the container (step 5); deriving and publishing artifacts, and deprecating the ORM
(ord-schema); paging past 1,000 results.
