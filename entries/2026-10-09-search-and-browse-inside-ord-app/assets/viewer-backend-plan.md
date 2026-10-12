# The viewer's backend: implementation plan for L1, L2, and V1–V4

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; not started
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ord-app's Python into `backend/editor` as `ord_editor` (L1) and its image
files into `deploy/editor` (L2), then build `backend/viewer`, the viewer's search and
browse API on `ord_schema.search` (V1–V4).

**Architecture:** L1 and L2 are pure moves: no behavior changes, and every gate keeps its
name. V1 adds a second uv project whose FastAPI app opens one `Corpus` in its lifespan
and holds it for the life of the process; V2 adds the record routes (datasets, reactions,
downloads), V3 the search route with its error mapping and concurrency cap, and V4
`/ask`. Every viewer route reads the corpus through `request.app.state`, and tests run
against a corpus the session derives from reactions built in the conftest.

**Tech Stack:** uv, Python 3.12, FastAPI, pydantic-settings, ord-schema 0.9.1 with its
`search` and `nl` extras (DuckDB, RDKit 2026.3.5, anthropic), pytest with xdist, ruff
0.9.10, ty, pre-commit through `uvx`, Docker BuildKit, and one path in
ord-infrastructure's Pulumi stack.

**Spec:** [`viewer-backend-design.md`](viewer-backend-design.md), beside this file. Read
it first. Where this plan refines the design, the
[Refinements](#refinements-to-the-design) section says how, and the design has been
updated to match.

## Global Constraints

- Repository: `open-reaction-database/ord-app`, main checkout `~/ord/ord-app`. Every PR
  gets its own worktree at `~/ord/worktrees/ord-app/<branch>`, branched from an
  up-to-date `origin/main` after the previous PR has merged:

  ```bash
  git -C ~/ord/ord-app fetch origin
  git -C ~/ord/ord-app worktree add -b <branch> ~/ord/worktrees/ord-app/<branch> origin/main
  cd ~/ord/worktrees/ord-app/<branch>
  (cd frontend && npm ci --ignore-scripts)   # the pre-commit hooks and E2E use its tools
  ```

  Every command in a PR's tasks runs in that worktree. Leave the main checkout's branch
  alone: the user or another session may be using it. Once the PR merges, remove the
  worktree with `git -C ~/ord/ord-app worktree remove ~/ord/worktrees/ord-app/<branch>`.
  Never commit to `main`; never force-push.
- Order: L1, L2 (with its ord-infrastructure PR), V1, V2, V3, V4.
- L1 and L2 change no behavior. Existing test assertions stay as they are; only paths and
  import names change. CI job names stay `test_python`, `test_e2e`, `check_python`,
  `check_duplication`, `check_license_headers`, `lint_and_build_ui`, and `test_ui`. V1
  adds `test_python_viewer`.
- The editor's environment variables keep their names (`PG_DSN`, `ORD_APP_E2E`,
  `ORD_APP_TESTING`, `ORD_APP_REQUIRE_AUTH0`, `VITE_AUTH0_*`, `DOWNLOAD_LINK_SECRET`).
  Only the Python package is renamed.
- Both projects use Python 3.12 (`requires-python = ">=3.12,<3.13"`).
- `backend/viewer` pins `ord-schema[search,nl]==0.9.1` and `rdkit==2026.3.5`, and its dev
  group pins `ruff==0.9.10` so the pre-commit hook and CI agree.
- Every new `.py`, `.toml`, `.yaml`, `.sh`, and `Makefile` starts with the Apache-2.0
  header, copyright 2026, "Open Reaction Database Project Authors" (addlicense adds it;
  code blocks below omit it). A moved file keeps its header.
- Python style: no lazy imports; free functions rather than `@staticmethod`; Google-style
  docstrings whose first line fits on one line; no abbreviated words in identifiers;
  American spelling; comments describe the code as it is, never the change.
- Tests sit beside the code as `*_test.py`. Run them with `uv run pytest -n auto`.
- Shell commands are for zsh: quote globs meant for a program, and pass lists as arrays.
- Commit messages end with the `Co-Authored-By:` trailer naming the model you run as. PR
  bodies use `## Summary`, `## Changes`, `## Testing`, `## Notes` (delete an empty
  section), one line per paragraph, and end with the Claude Code footer.
- Files under `.claude/skills/` are write-protected in the sandbox; ask the user before
  editing one.

## Review Focus

Inputs the design implies but states no behavior for, most likely to bite first. Each
has a test in the task named.

1. **A compound with no structural identifier**, such as a catalyst given only by name:
   its molblock slot is `null` and the reaction still returns 200 (V2.2, `ord-viewer0202`).
2. **Repeated and unknown IDs in `GET /api/reactions`:** each known reaction once, in the
   order first asked; all unknown is `[]`, not 404; a single unknown ID on
   `/api/reactions/{id}` is 404 (V2.2).
3. **A search that matches nothing:** `{kind: "reactions", reaction_ids: [], truncated:
   false}` with 200, not 404 (V3.2).
4. **A slot after an error:** a search that fails with 422 frees its slot, so the next
   request on a one-slot service succeeds; the dataset charts' route waits for a slot like
   a search does (V3.1, V3.2).
5. **A question that is only whitespace:** 422 before any model call, so the stub client
   records no request (V4.1).

---

## PR L1: the editor's Python moves into `backend/editor`

Branch `backend-editor-layout`, in its own worktree from `origin/main`.

Open PRs that touch the backend (ord-app#817, #829, #834, #847) already need a rebase
past the frontend's move to `frontend/`; L1 adds the rename to that. Say so in the PR's
Notes.

### Task L1.1: Move and rename the package; one ruff config at the root

**Files:**

- Move: `ord_app/` → `backend/editor/ord_editor/`; `pyproject.toml`, `uv.lock`,
  `alembic.ini`, `migrations/`, `Dockerfile`, `entrypoint.sh` → `backend/editor/`
- Delete: `MANIFEST.in`, `.pylintrc`
- Create: `ruff.toml`, `backend/editor/.dockerignore`
- Modify: every `backend/editor/**/*.py` that names `ord_app`;
  `backend/editor/pyproject.toml`; `backend/editor/uv.lock` (regenerated);
  `backend/editor/ord_editor/.env.template`; `backend/editor/Dockerfile`;
  `backend/editor/entrypoint.sh`

**Interfaces:**

- Produces: the import package `ord_editor` (formerly `ord_app`); the uv project at
  `backend/editor` named `ord-editor`; the root `ruff.toml` whose `src` later tasks extend.

- [ ] **Step 1: Worktree and baseline.** Create the worktree for `backend-editor-layout`
  as the Global Constraints show, then from it:

  ```bash
  docker compose up -d db     # Postgres on localhost:5400, user and database "ord"
  uv sync --frozen --no-build
  uv run --frozen --no-build alembic upgrade head
  uv run --frozen --no-build pytest -n auto -q 2>&1 | tail -1
  ```

  Expected: a final line of the form `N passed`. Record N; L1 must end with the same N.

- [ ] **Step 2: Move.**

  ```bash
  mkdir -p backend/editor
  git mv ord_app backend/editor/ord_editor
  git mv pyproject.toml uv.lock alembic.ini migrations Dockerfile entrypoint.sh backend/editor/
  git rm -q MANIFEST.in .pylintrc
  ```

- [ ] **Step 3: Rename the imports.** Rewrite `ord_app` only where a `.` or `/` follows,
  which leaves the `ord_app_e2e` settings alias (the `ORD_APP_E2E` variable) alone.

  ```bash
  git ls-files -z 'backend/editor/*.py' 'backend/editor/ord_editor/.env.template' \
    | xargs -0 perl -pi -e 's/\bord_app(?=[.\/])/ord_editor/g'
  git grep -n 'ord_app' -- backend/editor ':!backend/editor/uv.lock'
  ```

  Expected: one line, `backend/editor/ord_editor/service_api/settings.py:34:` with
  `validation_alias="ord_app_e2e"`. The conftest's comment now reads "base_dir is
  ord_editor/service_api; testdata lives at ord_editor/testdata", and the `.env.template`
  line reads "Copy to ord_editor/.env."; change that one to "Copy to
  backend/editor/ord_editor/.env." by hand.

- [ ] **Step 4: The project file.** In `backend/editor/pyproject.toml`:

  - `name = "ord-app"` → `name = "ord-editor"`; `description = "The Open Reaction
    Database editor's backend"`.
  - Remove `"pre-commit>=4.0,<5",` from the `dev` group: pre-commit runs through `uvx`
    once there is no project at the root.
  - In `[tool.pytest.ini_options]`, the comment's "Shared fixtures/helpers live in
    ord_app/conftest.py." → "ord_editor/conftest.py.", and `testpaths = ["ord_editor"]`.
  - Delete every `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`,
    `[tool.ruff.lint.isort]`, and `[tool.ruff.format]` table with its comments (Step 5
    moves them to the root).
  - The closing ty comment becomes:

    ```toml
    # ty is invoked as `ty check ord_editor` by CI and the pre-commit hook, so no input
    # globs are configured here; ord_editor ships no generated sources, so no excludes are
    # needed. ty type-checks the test suite too, which is intentional.
    ```

- [ ] **Step 5: The root `ruff.toml`.** Ruff reads the closest configuration file and
  skips a `pyproject.toml` with no `[tool.ruff]` table, so one file at the root serves
  every project.

  ```toml
  # One ruff configuration for every Python project in the repository. The projects'
  # pyproject.toml files carry no [tool.ruff] table, so ruff finds this file from any of
  # them.
  line-length = 88
  indent-width = 4
  target-version = "py312"
  # Directories holding first-party packages, for import sorting.
  src = ["backend/editor"]

  [lint]
  # pycodestyle errors and warnings (E/W), pyflakes (F), import sorting (I), bugbear (B),
  # pyupgrade (UP), flake8-simplify (SIM), full type annotations (ANN: arguments,
  # *args/**kwargs, return types, and no bare Any), flake8-fastapi (FAST), and
  # flake8-bandit (S: security findings).
  select = ["E", "F", "W", "I", "B", "UP", "SIM", "ANN", "FAST", "S"]
  # E501 (line length) is the formatter's job; SIM108 (ternaries aren't always clearer);
  # B008 (function calls in argument defaults are fine here, e.g. FastAPI Depends).
  # ANN401 (no bare `Any`): `Any` is the honest type for **kwargs forwarded to
  # HTTPException/SQLAlchemy filters and for pydantic "before" validators that receive raw
  # input; annotating those as `object` breaks type checking.
  ignore = ["E501", "SIM108", "B008", "ANN401"]
  fixable = ["ALL"]
  unfixable = []
  # Allow unused variables when underscore-prefixed.
  dummy-variable-rgx = "^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$"

  [lint.per-file-ignores]
  # Tests trip B011 (`assert False`) and B017 (`pytest.raises(Exception)`); annotations
  # (ANN) add little on test functions; S101 flags `assert`, which is how pytest checks.
  "**/*_test.py" = ["B011", "B017", "ANN", "S101"]
  "**/conftest.py" = ["B011", "B017", "ANN", "S101"]

  [lint.isort]
  # ord_schema is an external dependency; pin its classification so import ordering is
  # deterministic even when the environment is not fully resolved.
  known-third-party = ["ord_schema"]

  [format]
  # Like Black: double quotes, space indent, respect magic trailing commas.
  quote-style = "double"
  indent-style = "space"
  skip-magic-trailing-comma = false
  line-ending = "auto"
  ```

- [ ] **Step 6: The compose image.** In `backend/editor/Dockerfile`, the build context
  becomes `backend/editor`: `COPY ord_app/ ./ord_app` → `COPY ord_editor/ ./ord_editor`
  (the other `COPY` lines are already relative to it). In `backend/editor/entrypoint.sh`:
  `exec uvicorn ord_editor.service_api.main:app --host 0.0.0.0 --port 8000 --reload`.
  Create `backend/editor/.dockerignore` for that context:

  ```text
  .venv/
  **/__pycache__/
  .pytest_cache/
  .ruff_cache/
  .coverage
  htmlcov/
  ord_editor/.env
  ```

- [ ] **Step 7: Lock, and check that only the name and pre-commit changed.**

  ```bash
  cd backend/editor
  uv lock
  git diff uv.lock | grep -E '^[-+]version' ; echo "exit $?"
  git diff uv.lock | grep -E '^[-+]name'
  ```

  Expected: the first grep prints nothing and `exit 1`; the second shows
  `ord-app` → `ord-editor` and removals only (`pre-commit` and the packages only it
  needed, such as `cfgv`, `identify`, `nodeenv`, `virtualenv`). A changed version is a bug
  in the move.

- [ ] **Step 8: Lint, type-check, and test from the project.**

  ```bash
  uv sync --frozen --no-build
  uv run --frozen --no-build ruff check --show-settings ord_editor/service_api/main.py | grep -i 'settings path'
  uv run --frozen --no-build ruff check ord_editor/
  uv run --frozen --no-build ruff format --check ord_editor/
  uv run --frozen --no-build ty check ord_editor
  uv run --frozen --no-build alembic upgrade head
  uv run --frozen --no-build pytest -n auto -q 2>&1 | tail -1
  cd ../..
  ```

  Expected: the settings path is `~/ord/ord-app/ruff.toml`; ruff, format, and ty clean;
  `N passed`, the baseline's N. If ruff reports import-order changes, `src` is wrong.

- [ ] **Step 9: Commit.**

  ```bash
  git status --short     # look for debris under backend/editor before staging it
  git add backend/editor ruff.toml
  git status --short     # every line staged: the first column filled, the second blank
  git commit -m "Move the editor's Python into backend/editor as ord_editor"
  ```

  (`git mv` and `git rm` staged the moves and removals already.)

### Task L1.2: Point the tooling, CI, images, and docs at the new paths

**Files:** `.pre-commit-config.yaml`, `.github/workflows/tests.yml`,
`.github/workflows/checks.yml`, `.github/dependabot.yml`, `.jscpd.json`, `Makefile`,
`docker-compose.yml`, `Dockerfile.single`, `supervisord.conf`, `.dockerignore`,
`scripts/dev-e2e.sh`, `CLAUDE.md`, `README.md`,
`.claude/skills/ord-app-ui-testing/SKILL.md`,
`frontend/apps/editor/src/common/constants/fieldLimits.ts`

**Interfaces:**

- Consumes: `backend/editor` and `ord_editor` from L1.1.
- Produces: CI steps that run from `backend/editor` (V1 adds parallel steps for
  `backend/viewer`); pre-commit hooks with ids `ruff`, `ruff-format`, `ty-editor`.

- [ ] **Step 1: pre-commit.** In `.pre-commit-config.yaml`, replace the ruff and ty
  blocks with:

  ```yaml
    # Python lint + format, scoped to the packages so the generated alembic migrations
    # stay untouched. CI runs the same checks from each project's directory.
    - repo: https://github.com/astral-sh/ruff-pre-commit
      # Keep in sync with the ruff version pinned in each project's uv.lock so the hook
      # and the `ruff format --check` CI step never disagree.
      rev: 41d2daf392fbf43341a77f24a9c6481a4b66af98  # frozen: v0.9.10
      hooks:
        - id: ruff
          args: [--fix]
          files: ^backend/editor/ord_editor/
        - id: ruff-format
          files: ^backend/editor/ord_editor/

    # Type checking. ty resolves imports through the project's uv environment, so each
    # project's hook runs from that project's directory.
    - repo: local
      hooks:
        - id: ty-editor
          name: ty check (backend/editor)
          entry: uv run --directory backend/editor ty check ord_editor
          language: system
          files: ^backend/editor/ord_editor/.*\.py$
          pass_filenames: false
  ```

  and in the jscpd hook, `files: ^(backend/editor/ord_editor|frontend/(apps|packages)/[^/]+/src)/.*\.(py|ts|tsx)$`.

- [ ] **Step 2: `.github/workflows/checks.yml`.**

  - `check_license_headers`: delete the `Install dependencies` step, and run the hook
    with `run: uvx --from 'pre-commit>=4,<5' pre-commit run addlicense --all-files --show-diff-on-failure`.
  - `check_python`: give each `run` step `working-directory: backend/editor`, and check
    `ord_editor` instead of `ord_app`:

    ```yaml
          - name: Install dependencies
            working-directory: backend/editor
            run: uv sync --frozen --no-build

          - name: ruff
            working-directory: backend/editor
            run: uv run --frozen --no-build ruff check ord_editor/

          - name: ruff format
            working-directory: backend/editor
            run: uv run --frozen --no-build ruff format --check ord_editor/

          - name: ty
            working-directory: backend/editor
            run: uv run --frozen --no-build ty check ord_editor
    ```

  - `check_duplication`'s comment: "so it scans backend/editor/ord_editor (Python) and
    the frontend workspaces' src/ trees (TS/TSX) per .jscpd.json."

- [ ] **Step 3: `.github/workflows/tests.yml`.**

  - `test_python`: add to the job

    ```yaml
        defaults:
          run:
            working-directory: backend/editor
    ```

    change `--cov=ord_app` to `--cov=ord_editor`, and the coverage upload's
    `path: htmlcov/` to `path: backend/editor/htmlcov/` (artifact paths are relative to
    the workspace, not the working directory).
  - `test_e2e`: add `working-directory: backend/editor` to `Install Python dependencies`
    and `Run alembic migrations`; in `Start servers and run E2E`, the backend line becomes

    ```bash
    nohup uv run --directory backend/editor --frozen --no-build uvicorn ord_editor.service_api.main:app --host 127.0.0.1 --port 8000 > /tmp/backend.log 2>&1 &
    ```

- [ ] **Step 4: Dependabot, jscpd, Makefile.**

  - `.github/dependabot.yml`, the docker entry: `directory: /` →

    ```yaml
        directories:
          - /
          - /backend/editor
    ```

    (`Dockerfile.single` stays at the root until L2.)
  - `.jscpd.json`: `"path": ["backend/editor/ord_editor", "frontend/apps/editor/src", "frontend/packages/ui/src"]`.
  - `Makefile`, below its license header (each recipe line starts with a tab, shown here as
    four spaces):

    ```make
    .PHONY: duplication check-ruff python-formatting python-checking

    duplication:
        frontend/node_modules/.bin/jscpd --config .jscpd.json

    check-ruff:
        uv run --directory backend/editor ruff check ord_editor/

    python-formatting:
        uv run --directory backend/editor ruff check ord_editor/ --fix

    python-checking: check-ruff
        uv run --directory backend/editor ty check ord_editor
    ```

    `check-pytype` goes (pytype is not installed), and `python-formating` is spelled
    `python-formatting`; list both in the PR's Notes.

- [ ] **Step 5: Compose, the production image, the dev script.**

  - `docker-compose.yml`: the `api` service's `build.context: backend/editor` (keep
    `dockerfile: Dockerfile`), and in `api` and `migrate`, `- .:/app` →
    `- ./backend/editor:/app`.
  - `Dockerfile.single` (still at the root; context is the repository):

    ```dockerfile
    COPY backend/editor/uv.lock backend/editor/pyproject.toml ./
    RUN uv sync --frozen --no-dev --no-build

    COPY backend/editor/ord_editor/ ./ord_editor
    ```

  - `supervisord.conf`: `command=uvicorn ord_editor.service_api.main:app --host 0.0.0.0 --port 8000 --workers 3`.
  - `.dockerignore` (the root one, which `Dockerfile.single` uses): delete the
    `ord_app/tests/`, `.pylintrc`, `MANIFEST.in`, and `Dockerfile` lines; fix
    `__pychace__/` to `**/__pycache__/`; change `.venv/` to `**/.venv/`.
  - `scripts/dev-e2e.sh`:
    `uv run --directory backend/editor --frozen --no-build alembic upgrade head` and
    `uv run --directory backend/editor --frozen --no-build uvicorn ord_editor.service_api.main:app --host 127.0.0.1 --port 8000 &`.

- [ ] **Step 6: Docs.**

  - `CLAUDE.md`, Layout: replace the `ord_app/` bullet and its two children, and the
    `migrations/` line, with

    ```markdown
    - `backend/editor/` — the editor's backend, its own uv project (Python 3.12): `pyproject.toml`, `uv.lock`, `alembic.ini`, `migrations/` (Alembic), and the compose image's `Dockerfile`.
      - `ord_editor/service_api/` — FastAPI app (`service_api/main.py`), `repositories/`, `services/`, `domain/`, `schemas/`, `resources/`. Served under `/service_api`. Tests sit beside the code as `*_test.py`; shared fixtures in `ord_editor/conftest.py`, data in `ord_editor/testdata/`.
    - `ruff.toml` — the ruff config for every Python project. `scripts/` — dev/E2E helpers. `docker-compose.yml` — Postgres + the editor's backend.
    ```

  - `CLAUDE.md`, Backend: the heading becomes `## Backend (Python, uv)` with a first
    bullet "Each project under `backend/` is its own uv project; run its commands from its
    directory (`cd backend/editor`) or with `uv run --directory backend/editor …`."; the
    dev server line becomes `cd backend/editor/ord_editor/service_api && ORD_APP_TESTING=TRUE uv run fastapi dev main.py`;
    and the lint line `uv run ty check ord_editor`, with "config in the root `ruff.toml`".
  - `CLAUDE.md`, Formatting & pre-commit: `uv run pre-commit install` → `uvx pre-commit install`;
    "(scoped to `ord_app/`)" → "(scoped to `backend/editor/ord_editor/`)";
    `uv run pre-commit run --all-files` → `uvx pre-commit run --all-files`.
  - `CLAUDE.md`, Conventions: "or `ord_app/.env`" → "or `backend/editor/ord_editor/.env`".
  - `README.md`, Local development: Python 3.12 and uv instead of "Python >= 3.10"; step 2
    becomes `cd backend/editor && uv sync --frozen`; step 3's directory becomes
    `backend/editor/ord_editor/service_api` and its command `ORD_APP_TESTING=TRUE uv run fastapi dev main.py`.
    Code style: `uvx pre-commit install` and `uvx pre-commit run --all-files`.
  - `.claude/skills/ord-app-ui-testing/SKILL.md` (ask the user first; the path is
    write-protected): `uv run alembic upgrade head` →
    `uv run --directory backend/editor alembic upgrade head`, and the uvicorn line →
    `uv run --directory backend/editor uvicorn ord_editor.service_api.main:app --host 127.0.0.1 --port 8000 &`.
  - `frontend/apps/editor/src/common/constants/fieldLimits.ts:21`: the comment's path →
    `backend/editor/ord_editor/service_api/schemas/base.py`.

- [ ] **Step 7: Nothing names the old package.**

  ```bash
  git grep -n -w 'ord_app' -- . ':!backend/editor/uv.lock' ; echo "exit $?"
  ```

  Expected: no lines, `exit 1` (`-w` skips `ord_app_e2e`).

- [ ] **Step 8: Hooks, images, and the stack.**

  ```bash
  uvx --from 'pre-commit>=4,<5' pre-commit run --all-files
  docker build -f Dockerfile.single \
    --build-arg VITE_AUTH0_DOMAIN=example.invalid --build-arg VITE_AUTH0_CLIENT_ID=layout \
    --build-arg VITE_AUTH0_AUDIENCE=layout --build-arg VITE_AUTH0_ISSUER=layout \
    --build-arg VITE_AUTH0_SCOPE=layout -t ord-editor:layout .
  docker run --rm -e APP_ENV=localhost --entrypoint python ord-editor:layout \
    -c "import ord_editor.service_api.main"
  docker compose build api && docker compose up -d db api
  for _ in {1..30}; do curl -sf http://localhost:8000/service_api/docs > /dev/null && break || sleep 2; done
  curl -sf -o /dev/null -w '%{http_code}\n' http://localhost:8000/service_api/docs
  docker compose down
  ```

  Expected: every hook passes; the image builds and the import succeeds; the compose
  backend answers `200`. The image is only otherwise built by Pulumi at deploy, so a
  broken `COPY` would surface there.

- [ ] **Step 9: E2E.** Boot the no-auth stack and run Playwright as the
  `ord-app-ui-testing` skill describes (Postgres from compose, the backend through
  `uv run --directory backend/editor`, the editor's dev server with
  `VITE_E2E_NO_AUTH=TRUE` and `VITE_API_ENDPOINT`). Expected: the same specs pass as on
  `main`; screenshot comparisons are CI-only.

- [ ] **Step 10: Commit.**

  ```bash
  git status --short     # only the files listed in this task
  git add .pre-commit-config.yaml .github/workflows/tests.yml .github/workflows/checks.yml \
    .github/dependabot.yml .jscpd.json Makefile docker-compose.yml Dockerfile.single \
    supervisord.conf .dockerignore scripts/dev-e2e.sh CLAUDE.md README.md \
    .claude/skills/ord-app-ui-testing/SKILL.md \
    frontend/apps/editor/src/common/constants/fieldLimits.ts
  git commit -m "Run the tooling, CI, and images from backend/editor"
  ```

### Task L1.3: Open PR L1

- [ ] **Step 1:** `git push -u origin backend-editor-layout`, then open the PR, titled
  "Move the editor's Python into backend/editor", with a body that states: the moves and
  the rename; that the lockfile changed only the project name and dropped pre-commit
  (now run with `uvx`); that one root `ruff.toml` replaces `[tool.ruff]`; the Makefile's
  renamed and removed targets; that the job names are unchanged; the test count N; and,
  under Notes, the open PRs that will need a rebase (#817, #829, #834, #847).
- [ ] **Step 2:** Check CI once, then go on; work Greptile's and SonarCloud's findings
  with the `review-pr` skill. After merge, remove the worktree.

---

## PR L2: the editor's image files move into `deploy/editor`

Branch `deploy-editor-layout`, in its own worktree from `origin/main` after L1 merges.
Its ord-infrastructure counterpart, branch `ord-app-deploy-editor`, merges after it and
before the next deploy.

### Task L2.1: Move the image files

**Files:**

- Move: `Dockerfile.single` → `deploy/editor/Dockerfile`; `nginx.conf`,
  `supervisord.conf` → `deploy/editor/`; `entrypoint_single.sh` →
  `deploy/editor/entrypoint.sh`; `.dockerignore` → `deploy/editor/Dockerfile.dockerignore`
- Modify: `deploy/editor/Dockerfile`, `deploy/editor/Dockerfile.dockerignore`,
  `.github/dependabot.yml`, `CLAUDE.md`

**Interfaces:**

- Produces: `deploy/editor/Dockerfile`, built with the repository root as context. BuildKit
  reads `deploy/editor/Dockerfile.dockerignore` for it and ignores any root
  `.dockerignore`, so each image keeps its own ignore list. Step 4's `deploy/viewer` follows
  the same pattern.

- [ ] **Step 1: Move.** Create the worktree for `deploy-editor-layout` as the Global
  Constraints show, then from it:

  ```bash
  mkdir -p deploy/editor
  git mv Dockerfile.single deploy/editor/Dockerfile
  git mv nginx.conf supervisord.conf deploy/editor/
  git mv entrypoint_single.sh deploy/editor/entrypoint.sh
  git mv .dockerignore deploy/editor/Dockerfile.dockerignore
  ```

- [ ] **Step 2: Paths inside the Dockerfile.** The context stays the repository root:

  ```dockerfile
  COPY deploy/editor/nginx.conf /etc/nginx/nginx.conf
  ```

  ```dockerfile
  COPY deploy/editor/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
  ```

  ```dockerfile
  COPY deploy/editor/entrypoint.sh ./
  RUN chmod +x ./entrypoint.sh
  ```

  ```dockerfile
  ENTRYPOINT ["sh", "./entrypoint.sh"]
  ```

- [ ] **Step 3: The ignore file.** In `deploy/editor/Dockerfile.dockerignore`, drop the
  lines naming files that no longer sit at the root (`Dockerfile.single`) and add:

  ```text
  .git/
  backend/viewer/
  deploy/viewer/
  ```

  (`frontend/apps/viewer` must stay: `npm ci` installs every workspace the lockfile
  names.)

- [ ] **Step 4: Dependabot and docs.** In `.github/dependabot.yml`, the docker entry's
  `directories` become `/backend/editor` and `/deploy/editor`. In `CLAUDE.md`, add to
  Layout "`deploy/editor/` — the editor's production image: `Dockerfile` (the editor's
  bundle and backend behind nginx, under supervisord), `Dockerfile.dockerignore`,
  `nginx.conf`, `supervisord.conf`, `entrypoint.sh`.", and in Conventions "Image builds
  (`Dockerfile.single`)" → "Image builds (`deploy/editor/Dockerfile`)".

- [ ] **Step 5: Build and run.**

  ```bash
  docker build -f deploy/editor/Dockerfile \
    --build-arg VITE_AUTH0_DOMAIN=example.invalid --build-arg VITE_AUTH0_CLIENT_ID=layout \
    --build-arg VITE_AUTH0_AUDIENCE=layout --build-arg VITE_AUTH0_ISSUER=layout \
    --build-arg VITE_AUTH0_SCOPE=layout -t ord-editor:deploy . 2>&1 | grep -i 'transferring context'
  docker run --rm --entrypoint nginx ord-editor:deploy -t
  docker run --rm --entrypoint sh ord-editor:deploy -c \
    'test -x ./entrypoint.sh && grep -q ord_editor /etc/supervisor/conf.d/supervisord.conf && echo ok'
  docker run --rm -e APP_ENV=localhost --entrypoint python ord-editor:deploy \
    -c "import ord_editor.service_api.main"
  docker run --rm --entrypoint sh ord-editor:deploy -c \
    'find /app \( -name "*_test.py" -o -name conftest.py -o -name testdata -o -name .env \) -print'
  ```

  Expected: a context far smaller than L1's build (`.git/` is no longer sent); `nginx -t`
  reports the configuration ok; `ok`; the import succeeds; `find` prints nothing, so L1's
  exclusions came along with the ignore file.

- [ ] **Step 6: Commit and open the PR.**

  ```bash
  git add deploy/editor .github/dependabot.yml CLAUDE.md
  git add -u .
  git status --short
  git commit -m "Move the editor's image files into deploy/editor"
  git push -u origin deploy-editor-layout
  ```

  Title "Move the editor's image files into deploy/editor". Notes: the paired
  ord-infrastructure PR (Task L2.2) merges after this one and before the next deploy;
  until it does, `pulumi up` for `stacks/app` fails at the image build, naming the
  missing `Dockerfile.single`.

### Task L2.2: Point the app stack at the new Dockerfile

**Files:** in `~/ord/ord-infrastructure`, `stacks/app/__main__.py:101`

- [ ] **Step 1:**

  ```bash
  git -C ~/ord/ord-infrastructure fetch origin
  git -C ~/ord/ord-infrastructure worktree add -b ord-app-deploy-editor \
    ~/ord/worktrees/ord-infrastructure/ord-app-deploy-editor origin/main
  cd ~/ord/worktrees/ord-infrastructure/ord-app-deploy-editor
  ```

  In `stacks/app/__main__.py`, `dockerfile="../../../ord-app/Dockerfile.single",` →
  `dockerfile="../../../ord-app/deploy/editor/Dockerfile",`.
- [ ] **Step 2:** `uv sync --locked && uv run pytest -q`. Expected: green (the stack
  tests mock the build; `shared_test.py`'s Dockerfile paths are fixtures of their own).
  Never run `pulumi` from this worktree: the stacks find ord-app as `../../../ord-app`,
  which resolves only from the main checkout, `~/ord/ord-infrastructure`.
- [ ] **Step 3:** Commit ("Build ord-app's image from deploy/editor/Dockerfile"), push,
  and open the PR, linking PR L2. It merges after L2. The staging stack builds whatever
  ord-app has checked out, so a staging deploy from a branch older than L2 fails until
  that branch is rebased. After merge, remove the worktree with
  `git -C ~/ord/ord-infrastructure worktree remove ~/ord/worktrees/ord-infrastructure/ord-app-deploy-editor`.

---

## PR V1: the `backend/viewer` project

Branch `viewer-backend-project`, in its own worktree from `origin/main` after L2 merges.

### Task V1.1: The project, a derived test corpus, and `/api/health`

**Files:**

- Create: `backend/viewer/pyproject.toml`, `backend/viewer/uv.lock` (generated),
  `backend/viewer/ord_viewer/__init__.py`, `ord_viewer/settings.py`, `ord_viewer/state.py`,
  `ord_viewer/corpus.py`, `ord_viewer/main.py`, `ord_viewer/routes/__init__.py`,
  `ord_viewer/routes/health.py`, `ord_viewer/testing.py`, `ord_viewer/conftest.py`
  (paths below `ord_viewer/` are in `backend/viewer/`)
- Modify: `ruff.toml`
- Test: `ord_viewer/main_test.py`

**Interfaces:**

- Produces, for every later task:
  - `ord_viewer.settings.Settings` (pydantic-settings, prefix `ORD_VIEWER_`) with
    `corpus_dir: Path | None`, `memory_limit: str | None`, `max_concurrent: int` (≥ 1,
    default 4).
  - `ord_viewer.state.ViewerState`, a frozen dataclass with `settings: Settings` and
    `corpus: execute.Corpus`, and `get_state(request: Request) -> ViewerState`, the
    dependency every route takes as `state: Annotated[ViewerState, Depends(get_state)]`.
  - `ord_viewer.corpus.open_corpus(settings: Settings, *, resolver: Callable[[str], str]) -> execute.Corpus`
    and `ord_viewer.corpus.resolve_compound_name(name: str) -> str`.
  - `ord_viewer.main.create_app(settings_factory: Callable[[], Settings] = Settings, *, resolver: Callable[[str], str] = resolve_compound_name) -> FastAPI`
    and the module-level `app = create_app()`; the lifespan stores the state on
    `app.state.viewer`.
  - `ord_viewer.testing`: `DATASETS`, `offline_resolver(name: str) -> str`,
    `derive_corpus(root: pathlib.Path) -> None`,
    `make_client(corpus_dir: pathlib.Path, **settings: Any) -> TestClient`.
  - Fixtures in `ord_viewer/conftest.py`: `corpus_dir` (session) and `client` (session,
    entered).
  - The test corpus: dataset `ord_dataset-viewer01` ("viewer one": `ord-viewer0101`, a
    Suzuki coupling at 65% yield; `ord-viewer0102`, L-alanine acylated at 90%;
    `ord-viewer0103`, ethylamine acylated at 75%) and `ord_dataset-viewer02` ("viewer
    two": `ord-viewer0201`, D-alanine acylated at 40%; `ord-viewer0202`, an esterification
    with a catalyst given only by name, no yield).

- [ ] **Step 1: Worktree and project file.** Create the worktree for
  `viewer-backend-project` as the Global Constraints show, then from it:

  ```bash
  mkdir -p backend/viewer/ord_viewer/routes
  ```

  In `ruff.toml`, `src = ["backend/editor", "backend/viewer"]`, so import sorting treats
  `ord_viewer` as first-party.

  `backend/viewer/pyproject.toml`:

  ```toml
  [project]
  name = "ord-viewer"
  version = "0.1.0"
  description = "The Open Reaction Database viewer's backend"
  requires-python = ">=3.12,<3.13"
  dependencies = [
      "fastapi>=0.138.0,<0.200",
      # Corpus opens only artifacts stamped with the exact ord-schema and RDKit versions
      # of the serving process, so both follow the corpus ord-schema publishes.
      "ord-schema[search,nl]==0.9.1",
      "rdkit==2026.3.5",
      "pyarrow>=24,<25",
      "pydantic>=2.13,<3",
      "pydantic-settings>=2.14,<3",
      "uvicorn>=0.34.0,<0.35",
  ]

  [dependency-groups]
  dev = [
      "httpx>=0.28.1,<0.29",
      "pytest>=9.0.3,<10",
      "pytest-cov>=6.0.0,<7",
      "pytest-xdist>=3.6,<4",
      # The version the ruff pre-commit hook pins.
      "ruff==0.9.10",
      "ty>=0.0.51",
  ]

  [tool.uv]
  package = false

  [tool.pytest.ini_options]
  # Tests sit beside the code as <module>_test.py; fixtures live in ord_viewer/conftest.py.
  testpaths = ["ord_viewer"]
  python_files = ["*_test.py"]

  [tool.coverage.report]
  fail_under = 80
  ```

  ```bash
  cd backend/viewer && uv lock && uv sync --frozen --no-build && cd ../..
  ```

  Expected: the lock resolves `ord-schema 0.9.1`, `rdkit 2026.3.5`, `duckdb 1.5.5`, and
  `anthropic` 0.120 or later; `--no-build` succeeds, so every package has a wheel.

- [ ] **Step 2: The test corpus builder.** `ord_viewer/testing.py`:

  ```python
  """A small corpus built and derived the way ord-schema derives a published one."""

  import pathlib
  from collections.abc import Sequence
  from typing import Any

  from fastapi.testclient import TestClient
  from ord_schema import parquet
  from ord_schema.artifacts.scripts import (
      derive_occurrences,
      derive_pivots,
      derive_projection,
      derive_structures,
  )
  from ord_schema.proto import dataset_pb2, reaction_pb2

  from ord_viewer.main import create_app
  from ord_viewer.settings import Settings

  # Names offline_resolver knows; any other name raises, as ord-schema's resolvers do.
  COMPOUND_NAMES = {"pyridine": "c1ccncc1"}


  def offline_resolver(name: str) -> str:
      """Resolve a compound name from COMPOUND_NAMES without the network.

      Raises:
          ValueError: If the name is not in COMPOUND_NAMES.
      """
      try:
          return COMPOUND_NAMES[name]
      except KeyError:
          raise ValueError(f"Could not resolve name {name} to SMILES") from None


  def _reaction(
      reaction_id: str,
      *,
      reactants: Sequence[str],
      product: str,
      yield_percent: float | None = None,
      catalyst_name: str | None = None,
  ) -> reaction_pb2.Reaction:
      """Build a reaction from reactant SMILES, one product, and an optional yield."""
      reaction = reaction_pb2.Reaction(reaction_id=reaction_id)
      for smiles in reactants:
          component = reaction.inputs["reactants"].components.add(
              reaction_role=reaction_pb2.ReactionRole.REACTANT
          )
          component.identifiers.add(type="SMILES", value=smiles)
      if catalyst_name is not None:
          catalyst = reaction.inputs["catalysts"].components.add(
              reaction_role=reaction_pb2.ReactionRole.CATALYST
          )
          catalyst.identifiers.add(type="NAME", value=catalyst_name)
      outcome_product = reaction.outcomes.add().products.add()
      outcome_product.identifiers.add(type="SMILES", value=product)
      if yield_percent is not None:
          measurement = outcome_product.measurements.add(type="YIELD")
          measurement.percentage.value = yield_percent
      return reaction


  DATASETS = (
      dataset_pb2.Dataset(
          dataset_id="ord_dataset-viewer01",
          name="viewer one",
          description="A Suzuki coupling and two acylations",
          reactions=[
              _reaction(
                  "ord-viewer0101",
                  reactants=["OB(O)c1ccccc1", "Brc1ccncc1"],
                  product="c1ccc(-c2ccncc2)cc1",
                  yield_percent=65,
              ),
              _reaction(
                  "ord-viewer0102",
                  reactants=["C[C@@H](N)C(=O)O", "CC(=O)Cl"],
                  product="C[C@@H](NC(C)=O)C(=O)O",
                  yield_percent=90,
              ),
              _reaction(
                  "ord-viewer0103",
                  reactants=["CCN", "CC(=O)Cl"],
                  product="CCNC(C)=O",
                  yield_percent=75,
              ),
          ],
      ),
      dataset_pb2.Dataset(
          dataset_id="ord_dataset-viewer02",
          name="viewer two",
          description="A mirror-image acylation and a named catalyst",
          reactions=[
              _reaction(
                  "ord-viewer0201",
                  reactants=["C[C@H](N)C(=O)O", "CC(=O)Cl"],
                  product="C[C@H](NC(C)=O)C(=O)O",
                  yield_percent=40,
              ),
              _reaction(
                  "ord-viewer0202",
                  reactants=["CCO", "CC(=O)O"],
                  product="CCOC(C)=O",
                  catalyst_name="mystery catalyst",
              ),
          ],
      ),
  )


  def derive_corpus(root: pathlib.Path) -> None:
      """Write DATASETS as sources under root and derive every artifact the viewer reads."""
      for dataset in DATASETS:
          source = root / "sources" / "aa" / f"{dataset.dataset_id}.parquet"
          source.parent.mkdir(parents=True, exist_ok=True)
          parquet.save_dataset(dataset, source)
      derive_projection.main(
          derive_projection.parse_args(
              [
                  f"--input_pattern={root}/sources/*/*.parquet",
                  f"--output_dir={root}/projections",
              ]
          )
      )
      derive_structures.main(
          derive_structures.parse_args(
              [
                  f"--input_pattern={root}/projections/*/*.parquet",
                  f"--output_dir={root}/structures",
              ]
          )
      )
      derive_pivots.main(
          derive_pivots.parse_args(
              [
                  f"--input_pattern={root}/projections/*/*.parquet",
                  f"--output_dir={root}/pivots",
              ]
          )
      )
      derive_occurrences.main(
          derive_occurrences.parse_args(
              [f"--pivots_dir={root}/pivots", f"--output_dir={root}/occurrences"]
          )
      )


  def make_client(corpus_dir: pathlib.Path, **settings: Any) -> TestClient:
      """Return an unentered client over corpus_dir, with any settings overridden."""
      app = create_app(
          lambda: Settings(corpus_dir=corpus_dir, **settings), resolver=offline_resolver
      )
      return TestClient(app)
  ```

  `ord_viewer/conftest.py`:

  ```python
  """Session fixtures: one derived corpus and one client over it."""

  import pathlib
  from collections.abc import Iterator

  import pytest
  from fastapi.testclient import TestClient

  from ord_viewer.testing import derive_corpus, make_client


  @pytest.fixture(scope="session")
  def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
      root = tmp_path_factory.mktemp("corpus")
      derive_corpus(root)
      return root


  @pytest.fixture(scope="session")
  def client(corpus_dir: pathlib.Path) -> Iterator[TestClient]:
      with make_client(corpus_dir) as test_client:
          yield test_client
  ```

- [ ] **Step 3: Failing tests.** `ord_viewer/main_test.py`:

  ```python
  import re
  import shutil

  import pytest
  from fastapi.testclient import TestClient

  from ord_viewer.main import create_app
  from ord_viewer.settings import Settings
  from ord_viewer.testing import make_client, offline_resolver


  def test_health_returns_the_corpus_fingerprint(client):
      response = client.get("/api/health")
      assert response.status_code == 200
      fingerprint = response.json()["fingerprint"]
      assert re.fullmatch(r"[0-9a-f]{16}", fingerprint)
      assert fingerprint == client.app.state.viewer.corpus.fingerprint


  def test_startup_fails_without_a_corpus_directory():
      app = create_app(lambda: Settings(corpus_dir=None), resolver=offline_resolver)
      with pytest.raises(ValueError, match="ORD_VIEWER_CORPUS_DIR"), TestClient(app):
          pass


  @pytest.mark.parametrize("missing", ["pivots", "occurrences", "sources"])
  def test_startup_names_a_missing_tree(corpus_dir, tmp_path, missing):
      partial = tmp_path / "corpus"
      shutil.copytree(corpus_dir, partial)
      shutil.rmtree(partial / missing)
      with pytest.raises(FileNotFoundError, match=f"no {missing}/ directory"), make_client(partial):
          pass
  ```

  Run: `cd backend/viewer && uv run --frozen pytest -q ord_viewer/main_test.py`.
  Expected: errors at collection, `ModuleNotFoundError: No module named 'ord_viewer.main'`.

- [ ] **Step 4: Implement.** `ord_viewer/__init__.py`:

  ```python
  """The Open Reaction Database viewer's backend: search and browse over one corpus."""
  ```

  `ord_viewer/routes/__init__.py`: `"""The viewer's routes, each an APIRouter under /api."""`.

  `ord_viewer/settings.py`:

  ```python
  """Settings for the viewer's backend, read from ORD_VIEWER_* environment variables."""

  from pathlib import Path

  from pydantic import Field
  from pydantic_settings import BaseSettings, SettingsConfigDict


  class Settings(BaseSettings):
      """Where the corpus lives and how the service uses it."""

      model_config = SettingsConfigDict(env_prefix="ORD_VIEWER_")

      # A root holding projections/, structures/, pivots/, occurrences/, and sources/.
      corpus_dir: Path | None = None
      # DuckDB's memory_limit, such as "6500MiB"; DuckDB's default when unset.
      memory_limit: str | None = None
      # Searches and asks in flight at once; each search gets cores / max_concurrent
      # RDKit threads.
      max_concurrent: int = Field(default=4, ge=1)
  ```

  `ord_viewer/state.py`:

  ```python
  """What the app holds for the life of the process, and the dependency that reads it."""

  import dataclasses

  from fastapi import Request
  from ord_schema.search import execute

  from ord_viewer.settings import Settings


  @dataclasses.dataclass(frozen=True)
  class ViewerState:
      """The settings and the open corpus every route reads."""

      settings: Settings
      corpus: execute.Corpus


  def get_state(request: Request) -> ViewerState:
      """Return the state the lifespan stored on the app."""
      return request.app.state.viewer
  ```

  `ord_viewer/corpus.py`:

  ```python
  """Opening the corpus a deployment serves, and resolving the compound names queries use."""

  import os
  from collections.abc import Callable

  from ord_schema import resolvers
  from ord_schema.search import execute

  from ord_viewer.settings import Settings

  # The trees under the corpus directory. Each artifact tree holds one shard level of
  # files, as ord-data's data/<shard>/ does and the derive scripts mirror.
  _TREES = ("projections", "structures", "pivots", "occurrences", "sources")


  def resolve_compound_name(name: str) -> str:
      """Resolve a compound name to SMILES through ord-schema's resolvers.

      Args:
          name: A compound name from a query.

      Returns:
          The SMILES the first resolver to answer gives.

      Raises:
          ValueError: If no resolver knows the name.
      """
      smiles, _ = resolvers.resolve_name("name", name)
      return smiles


  def open_corpus(settings: Settings, *, resolver: Callable[[str], str]) -> execute.Corpus:
      """Open the corpus under settings.corpus_dir and publish every pivot level.

      Args:
          settings: The service's settings.
          resolver: Resolves compound names in queries to SMILES; raises ValueError for
              a name it does not know.

      Returns:
          The open corpus, warmed, with its pivots checked.

      Raises:
          ValueError: If ORD_VIEWER_CORPUS_DIR is not set.
          FileNotFoundError: If the corpus directory lacks one of its trees.
          execute.PairingError: If the artifacts are stale or do not form one corpus.
      """
      if settings.corpus_dir is None:
          raise ValueError("ORD_VIEWER_CORPUS_DIR is not set")
      root = settings.corpus_dir
      for tree in _TREES:
          if not (root / tree).is_dir():
              raise FileNotFoundError(f"{root} has no {tree}/ directory")
      corpus = execute.Corpus(
          str(root / "projections" / "*" / "*.parquet"),
          str(root / "structures" / "*" / "*.parquet"),
          resolver=resolver,
          threads=max(1, (os.cpu_count() or 1) // settings.max_concurrent),
          require_current=True,
          pivots_dir=str(root / "pivots"),
          require_pivots=True,
          occurrences_dir=str(root / "occurrences"),
          require_occurrences=True,
          memory_limit=settings.memory_limit,
          warm=True,
          max_rows=execute.DEFAULT_MAX_ROWS,
          sources_pattern=str(root / "sources" / "*" / "*.parquet"),
      )
      try:
          corpus.check_pivots()
      except BaseException:
          corpus.close()
          raise
      return corpus
  ```

  `ord_viewer/routes/health.py`:

  ```python
  """The load balancer's health check."""

  from typing import Annotated

  from fastapi import APIRouter, Depends
  from pydantic import BaseModel

  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api")


  class Health(BaseModel):
      """The corpus the process serves."""

      fingerprint: str


  @router.get("/health")
  def health(state: Annotated[ViewerState, Depends(get_state)]) -> Health:
      """Return the open corpus's fingerprint."""
      return Health(fingerprint=state.corpus.fingerprint)
  ```

  `ord_viewer/main.py`:

  ```python
  """The viewer's FastAPI app: one corpus, opened at startup and held until shutdown."""

  import contextlib
  from collections.abc import AsyncIterator, Callable

  from fastapi import FastAPI

  from ord_viewer.corpus import open_corpus, resolve_compound_name
  from ord_viewer.routes import health
  from ord_viewer.settings import Settings
  from ord_viewer.state import ViewerState


  def create_app(
      settings_factory: Callable[[], Settings] = Settings,
      *,
      resolver: Callable[[str], str] = resolve_compound_name,
  ) -> FastAPI:
      """Build the app; its lifespan reads the settings and opens the corpus.

      Uvicorn accepts no connection until the lifespan has opened the corpus, and exits
      non-zero if opening it raises.

      Args:
          settings_factory: Called once at startup; the default reads the environment.
          resolver: Resolves compound names in queries to SMILES.

      Returns:
          The app, with every route registered.
      """

      @contextlib.asynccontextmanager
      async def lifespan(app: FastAPI) -> AsyncIterator[None]:
          settings = settings_factory()
          corpus = open_corpus(settings, resolver=resolver)
          app.state.viewer = ViewerState(settings=settings, corpus=corpus)
          try:
              yield
          finally:
              corpus.close()

      app = FastAPI(title="Open Reaction Database viewer", lifespan=lifespan)
      app.include_router(health.router)
      return app


  app = create_app()
  ```

- [ ] **Step 5: Run.** `uv run --frozen pytest -n auto -q` (from `backend/viewer`).
  Expected: `5 passed`. If the corpus fixture fails in `derive_pivots`, run it alone with
  `-p no:xdist -x` to see the artifact error.

- [ ] **Step 6: Lint and commit.**

  ```bash
  uv run --frozen ruff check ord_viewer/ && uv run --frozen ruff format --check ord_viewer/
  uv run --frozen ty check ord_viewer
  cd ../..
  git add backend/viewer ruff.toml
  git commit -m "Add the viewer's backend project, with a derived test corpus"
  ```

  Expected: clean.

### Task V1.2: Tooling, CI, and docs for the second project

**Files:** `.pre-commit-config.yaml`, `.jscpd.json`, `.github/workflows/checks.yml`,
`.github/workflows/tests.yml`, `CLAUDE.md`, `README.md`, `backend/viewer/pyproject.toml`

**Interfaces:**

- Consumes: L1's per-step `working-directory` layout in `check_python`, and its hook ids.
- Produces: the job `test_python_viewer` and the hook `ty-viewer`.

- [ ] **Step 1: pre-commit and jscpd.**
  - `.pre-commit-config.yaml`: both ruff hooks get
    `files: ^backend/(editor/ord_editor|viewer/ord_viewer)/`; add beside `ty-editor`:

    ```yaml
        - id: ty-viewer
          name: ty check (backend/viewer)
          entry: uv run --directory backend/viewer ty check ord_viewer
          language: system
          files: ^backend/viewer/ord_viewer/.*\.py$
          pass_filenames: false
    ```

    and the jscpd hook's `files: ^(backend/(editor/ord_editor|viewer/ord_viewer)|frontend/(apps|packages)/[^/]+/src)/.*\.(py|ts|tsx)$`.
  - `.jscpd.json`: add `"backend/viewer/ord_viewer"` to `path`.

- [ ] **Step 2: CI.** In `.github/workflows/checks.yml`, `check_python` gains, after the
  editor's steps:

  ```yaml
        - name: Install dependencies (viewer)
          working-directory: backend/viewer
          run: uv sync --frozen --no-build

        - name: ruff (viewer)
          working-directory: backend/viewer
          run: uv run --frozen --no-build ruff check ord_viewer/

        - name: ruff format (viewer)
          working-directory: backend/viewer
          run: uv run --frozen --no-build ruff format --check ord_viewer/

        - name: ty (viewer)
          working-directory: backend/viewer
          run: uv run --frozen --no-build ty check ord_viewer
  ```

  In `.github/workflows/tests.yml`, a new job after `test_python`:

  ```yaml
    test_python_viewer:
      strategy:
        matrix:
          os: ["ubuntu-latest", "macos-latest"]
      runs-on: ${{ matrix.os }}
      defaults:
        run:
          working-directory: backend/viewer

      steps:
        - name: Check out repository
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

        - name: Install uv
          uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
          with:
            python-version: "3.12"

        - name: Install dependencies
          run: uv sync --frozen --no-build

        - name: Run tests
          run: uv run --frozen --no-build pytest -n auto -vv --cov=ord_viewer --cov-report=term-missing --durations=10
  ```

- [ ] **Step 3: The coverage floor.** From `backend/viewer`,
  `uv run --frozen pytest -n auto -q --cov=ord_viewer --cov-report=term | tail -3`. Set
  `[tool.coverage.report] fail_under` in `backend/viewer/pyproject.toml` to the TOTAL
  rounded down to a multiple of 5, and no lower than 80, with the comment
  `# A few points below the measured total, as a regression backstop; ratchet up over time.`

- [ ] **Step 4: Docs.**
  - `CLAUDE.md`, Layout, after the `backend/editor/` bullet:

    ```markdown
    - `backend/viewer/` — the viewer's backend, its own uv project (Python 3.12), pinned to `ord-schema[search,nl]==0.9.1` and `rdkit==2026.3.5` because `Corpus` opens only artifacts stamped with those exact versions. `ord_viewer/` — a FastAPI app with every route under `/api/`, serving one corpus directory (`ORD_VIEWER_CORPUS_DIR`: `projections/`, `structures/`, `pivots/`, `occurrences/`, `sources/`, each with one shard level). Tests derive a small corpus (`ord_viewer/testing.py`) and need no Postgres.
    ```

  - `CLAUDE.md`, Backend: a bullet "Viewer: `cd backend/viewer && uv sync --frozen`;
    tests `uv run pytest -n auto`; serve with
    `ORD_VIEWER_CORPUS_DIR=<corpus> uv run uvicorn ord_viewer.main:app --port 8001`
    (opening a full corpus takes about 40 s and 7 GiB)."
  - `CLAUDE.md`, CI gates: add `test_python_viewer` to the Tests line.
  - `README.md`: a "Viewer backend" subsection with the same three commands.

- [ ] **Step 5: Check and commit.**

  ```bash
  uvx --from 'pre-commit>=4,<5' pre-commit run --all-files
  git add .pre-commit-config.yaml .jscpd.json .github/workflows/checks.yml \
    .github/workflows/tests.yml CLAUDE.md README.md backend/viewer/pyproject.toml
  git commit -m "Lint, type-check, and test the viewer's backend in CI"
  ```

  Expected: every hook passes, `ty-viewer` included.

### Task V1.3: Open PR V1

- [ ] **Step 1:** Push and open "Add the viewer's backend project". Body: the project and
  its pins, the corpus layout it reads, the derived test corpus, `/api/health`, the new
  CI job, and the coverage floor. Notes: **`test_python_viewer` has to be added to the
  branch protection's required checks** (the user does this; ask them after merge).
- [ ] **Step 2:** Check CI once; work Greptile and SonarCloud with `review-pr`.

---

## PR V2: datasets, reactions, and downloads

Branch `viewer-backend-records`, in its own worktree from `origin/main` after V1 merges.

### Task V2.1: Datasets and their compound counts

**Files:**

- Create: `ord_viewer/schemas.py`, `ord_viewer/molblocks.py`, `ord_viewer/searching.py`,
  `ord_viewer/routes/datasets.py`
- Modify: `ord_viewer/settings.py`, `ord_viewer/main.py`
- Test: `ord_viewer/routes/datasets_test.py`

**Interfaces:**

- Consumes: `ViewerState`, `get_state`, the test corpus (V1.1).
- Produces:
  - `Settings.search_timeout_seconds: float` (> 0, default 30).
  - `ord_viewer.schemas`: `DatasetSummary(dataset_id: str, name: str, description: str, reactions: int)`,
    `CompoundCount(smiles: str, molblock: str | None, count: int)`.
  - `ord_viewer.molblocks.smiles_molblock(smiles: str) -> str | None`.
  - `ord_viewer.searching.search_errors()`, a context manager mapping `ValueError` (which
    includes `QueryError`, but not `PairingError`) to 422 and `TimeoutError` to 504, and
    `run_search(state: ViewerState, request: Query) -> pa.Table`.

- [ ] **Step 1: Failing tests.** `ord_viewer/routes/datasets_test.py`:

  ```python
  from rdkit import Chem


  def test_lists_datasets_by_name(client):
      response = client.get("/api/datasets")
      assert response.status_code == 200
      assert response.json() == [
          {
              "dataset_id": "ord_dataset-viewer01",
              "name": "viewer one",
              "description": "A Suzuki coupling and two acylations",
              "reactions": 3,
          },
          {
              "dataset_id": "ord_dataset-viewer02",
              "name": "viewer two",
              "description": "A mirror-image acylation and a named catalyst",
              "reactions": 2,
          },
      ]


  def test_gets_one_dataset(client):
      response = client.get("/api/datasets/ord_dataset-viewer02")
      assert response.status_code == 200
      assert response.json()["reactions"] == 2


  def test_an_unknown_dataset_is_not_found(client):
      assert client.get("/api/datasets/ord_dataset-nope").status_code == 404
      assert client.get("/api/datasets/ord_dataset-nope/compounds").status_code == 404


  def test_counts_input_compounds_most_used_first(client):
      response = client.get("/api/datasets/ord_dataset-viewer01/compounds")
      assert response.status_code == 200
      rows = response.json()
      assert Chem.CanonSmiles(rows[0]["smiles"]) == Chem.CanonSmiles("CC(=O)Cl")
      assert rows[0]["count"] == 2
      assert "M  END" in rows[0]["molblock"]
      assert len(rows) == 5


  def test_counts_products_and_skips_unstructured_inputs(client):
      products = client.get(
          "/api/datasets/ord_dataset-viewer02/compounds", params={"side": "products"}
      ).json()
      assert sorted(Chem.CanonSmiles(row["smiles"]) for row in products) == sorted(
          Chem.CanonSmiles(smiles) for smiles in ["C[C@H](NC(C)=O)C(=O)O", "CCOC(C)=O"]
      )
      inputs = client.get("/api/datasets/ord_dataset-viewer02/compounds").json()
      assert all(row["smiles"] for row in inputs)  # the named catalyst has no SMILES
      assert len(inputs) == 4


  def test_limits_the_compound_counts(client):
      params = {"limit": 1}
      assert len(client.get("/api/datasets/ord_dataset-viewer01/compounds", params=params).json()) == 1
      for bad in ({"limit": 0}, {"limit": 101}, {"side": "solvents"}):
          response = client.get("/api/datasets/ord_dataset-viewer01/compounds", params=bad)
          assert response.status_code == 422
  ```

  Run: `uv run --frozen pytest -q ord_viewer/routes/datasets_test.py`. Expected: 6
  failures, 404 for every route.

- [ ] **Step 2: Implement.** `Settings` gains

  ```python
      # The bound on one search, passed to Corpus.search; a search past it answers 504.
      search_timeout_seconds: float = Field(default=30.0, gt=0)
  ```

  `ord_viewer/schemas.py`:

  ```python
  """The bodies the routes accept and return."""

  from pydantic import BaseModel


  class DatasetSummary(BaseModel):
      """One dataset in the corpus, from its source file's footer."""

      dataset_id: str
      name: str
      description: str
      reactions: int


  class CompoundCount(BaseModel):
      """How many times one compound appears in a dataset, with a molblock to draw it."""

      smiles: str
      molblock: str | None
      count: int
  ```

  `ord_viewer/molblocks.py`:

  ```python
  """Molblocks for the browser, which draws molecules with Indigo rather than SVG."""

  from rdkit import Chem


  def smiles_molblock(smiles: str) -> str | None:
      """Return a molblock for a SMILES, or None if RDKit cannot read it."""
      molecule = Chem.MolFromSmiles(smiles)
      return None if molecule is None else Chem.MolToMolBlock(molecule)
  ```

  `ord_viewer/searching.py`:

  ```python
  """Running a query against the corpus, with its failures mapped to HTTP statuses."""

  import contextlib
  from collections.abc import Iterator

  import pyarrow as pa
  from fastapi import HTTPException, status
  from ord_schema.search import execute
  from ord_schema.search.query import Query

  from ord_viewer.state import ViewerState


  @contextlib.contextmanager
  def search_errors() -> Iterator[None]:
      """Map a query's failures to 422 and its timeout to 504.

      QueryError and an unresolved compound are ValueErrors; PairingError is one too, but
      it means the corpus is inconsistent, so it propagates as a server error.
      """
      try:
          yield
      except execute.PairingError:
          raise
      except ValueError as error:
          raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
      except TimeoutError as error:
          raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(error)) from error


  def run_search(state: ViewerState, request: Query) -> pa.Table:
      """Run one query under the service's timeout."""
      with search_errors():
          return state.corpus.search(
              request, timeout_seconds=state.settings.search_timeout_seconds
          )
  ```

  `ord_viewer/routes/datasets.py`:

  ```python
  """The datasets in the corpus, and the compounds their reactions use most."""

  from typing import Annotated, Literal

  from fastapi import APIRouter, Depends, HTTPException, Query, status
  from ord_schema.search import execute
  from ord_schema.search.query import Query as SearchQuery

  from ord_viewer.molblocks import smiles_molblock
  from ord_viewer.schemas import CompoundCount, DatasetSummary
  from ord_viewer.searching import run_search
  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api/datasets")

  # The repeated level each side's compounds live on.
  _LEVELS = {"inputs": "inputs.components", "products": "outcomes.products"}


  def _summaries(corpus: execute.Corpus) -> list[DatasetSummary]:
      """List the corpus's datasets by name.

      A source with no dataset ID can be neither addressed nor filtered on, so it is
      left out.
      """
      summaries = [
          DatasetSummary(**row)
          for row in corpus.datasets().to_pylist()
          if row["dataset_id"] is not None
      ]
      return sorted(summaries, key=lambda summary: summary.name)


  def _find(corpus: execute.Corpus, dataset_id: str) -> DatasetSummary:
      """Return one dataset's summary.

      Raises:
          HTTPException: 404, if the corpus holds no such dataset.
      """
      for summary in _summaries(corpus):
          if summary.dataset_id == dataset_id:
              return summary
      raise HTTPException(status.HTTP_404_NOT_FOUND, f"no dataset {dataset_id}")


  @router.get("")
  def list_datasets(
      state: Annotated[ViewerState, Depends(get_state)],
  ) -> list[DatasetSummary]:
      """Return every dataset, sorted by name."""
      return _summaries(state.corpus)


  @router.get("/{dataset_id}")
  def get_dataset(
      dataset_id: str, state: Annotated[ViewerState, Depends(get_state)]
  ) -> DatasetSummary:
      """Return one dataset."""
      return _find(state.corpus, dataset_id)


  @router.get("/{dataset_id}/compounds")
  def dataset_compounds(
      dataset_id: str,
      state: Annotated[ViewerState, Depends(get_state)],
      side: Literal["inputs", "products"] = "inputs",
      limit: Annotated[int, Query(ge=1, le=100)] = 30,
  ) -> list[CompoundCount]:
      """Return the compounds a dataset's inputs or products use most, most first."""
      _find(state.corpus, dataset_id)
      request = SearchQuery.model_validate(
          {
              "where": {"op": "eq", "path": "dataset_id", "value": {"literal": dataset_id}},
              "aggregate": {
                  "over": _LEVELS[side],
                  "where": {"op": "not_null", "path": "smiles"},
                  "group_by": ["smiles"],
                  "measures": [{"fn": "count", "name": "occurrences"}],
              },
              "order_by": [{"key": "occurrences", "descending": True}],
              "limit": limit,
          }
      )
      table = run_search(state, request)
      return [
          CompoundCount(
              smiles=row["smiles"],
              molblock=smiles_molblock(row["smiles"]),
              count=row["occurrences"],
          )
          for row in table.to_pylist()
      ]
  ```

  In `main.py`, import `datasets` from `ord_viewer.routes` and
  `app.include_router(datasets.router)`.

- [ ] **Step 3: Run.** `uv run --frozen pytest -n auto -q`. Expected: `11 passed`.
- [ ] **Step 4: Lint and commit** ("Serve the datasets and their compound counts").

### Task V2.2: Reactions with molblocks

**Files:**

- Modify: `ord_viewer/schemas.py`, `ord_viewer/molblocks.py`, `ord_viewer/main.py`
- Create: `ord_viewer/routes/reactions.py`
- Test: `ord_viewer/molblocks_test.py`, `ord_viewer/routes/reactions_test.py`

**Interfaces:**

- Produces:
  - `ord_viewer.schemas`: `AuthenticStandardMolblock(molblock: str | None)`,
    `MeasurementMolblocks(authentic_standard: AuthenticStandardMolblock)`,
    `ProductMolblocks(molblock: str | None, measurements: list[MeasurementMolblocks])`,
    `OutcomeMolblocks(products: list[ProductMolblocks])`,
    `ReactionMolblocks(inputs: dict[str, list[str | None]], outcomes: list[OutcomeMolblocks], workups: list[list[str | None]])`,
    `ReactionRecord(reaction_id: str, dataset_id: str | None, binpb: str, molblocks: ReactionMolblocks)`.
    This is the editor's `{inputs, outcomes, workups}` shape, which the shared package's
    `getReactionPreviews` reads.
  - `ord_viewer.molblocks.reaction_molblocks(reaction: reaction_pb2.Reaction) -> ReactionMolblocks`.
  - `ord_viewer.routes.reactions.fetch_records(corpus: execute.Corpus, reaction_ids: Sequence[str]) -> list[ReactionRecord]`.

- [ ] **Step 1: Failing tests.** `ord_viewer/molblocks_test.py`:

  ```python
  from ord_schema.proto import reaction_pb2

  from ord_viewer.molblocks import reaction_molblocks, smiles_molblock


  def test_every_slot_of_a_reaction():
      reaction = reaction_pb2.Reaction()
      reaction.inputs["solvent"].components.add().identifiers.add(type="SMILES", value="CCO")
      product = reaction.outcomes.add().products.add()
      product.identifiers.add(type="SMILES", value="CC=O")
      standard = product.measurements.add(type="YIELD").authentic_standard
      standard.identifiers.add(type="SMILES", value="CC=O")
      workup = reaction.workups.add(type="ADDITION")
      workup.input.components.add().identifiers.add(type="NAME", value="brine")

      molblocks = reaction_molblocks(reaction)

      assert "M  END" in molblocks.inputs["solvent"][0]
      assert "M  END" in molblocks.outcomes[0].products[0].molblock
      assert "M  END" in molblocks.outcomes[0].products[0].measurements[0].authentic_standard.molblock
      assert molblocks.workups == [[None]]  # a name alone has no structure


  def test_a_measurement_without_a_standard_has_no_molblock():
      reaction = reaction_pb2.Reaction()
      product = reaction.outcomes.add().products.add()
      product.identifiers.add(type="SMILES", value="C")
      product.measurements.add(type="YIELD")
      molblocks = reaction_molblocks(reaction)
      assert molblocks.outcomes[0].products[0].measurements[0].authentic_standard.molblock is None


  def test_unreadable_smiles_has_no_molblock():
      assert smiles_molblock("not a molecule") is None
  ```

  `ord_viewer/routes/reactions_test.py`:

  ```python
  import base64

  from ord_schema.proto import reaction_pb2


  def _get(client, *reaction_ids):
      return client.get("/api/reactions", params=[("id", reaction_id) for reaction_id in reaction_ids])


  def test_returns_reactions_in_the_order_asked(client):
      response = _get(client, "ord-viewer0102", "ord-viewer0101")
      assert response.status_code == 200
      records = response.json()
      assert [record["reaction_id"] for record in records] == ["ord-viewer0102", "ord-viewer0101"]
      assert records[0]["dataset_id"] == "ord_dataset-viewer01"
      reaction = reaction_pb2.Reaction.FromString(base64.b64decode(records[0]["binpb"]))
      assert reaction.reaction_id == "ord-viewer0102"
      molblocks = records[0]["molblocks"]
      assert all("M  END" in molblock for molblock in molblocks["inputs"]["reactants"])
      assert "M  END" in molblocks["outcomes"][0]["products"][0]["molblock"]
      assert molblocks["workups"] == []


  def test_a_compound_without_a_structure_has_a_null_molblock(client):
      record = client.get("/api/reactions/ord-viewer0202").json()
      assert record["molblocks"]["inputs"]["catalysts"] == [None]


  def test_repeated_and_unknown_ids(client):
      records = _get(client, "ord-viewer0101", "ord-viewer0101", "ord-unknown").json()
      assert [record["reaction_id"] for record in records] == ["ord-viewer0101"]
      assert _get(client, "ord-unknown").json() == []


  def test_one_reaction(client):
      assert client.get("/api/reactions/ord-viewer0201").json()["dataset_id"] == "ord_dataset-viewer02"
      assert client.get("/api/reactions/ord-unknown").status_code == 404


  def test_bounds_the_batch(client):
      assert client.get("/api/reactions").status_code == 422
      assert _get(client, *[f"ord-{index}" for index in range(101)]).status_code == 422
  ```

  Run both files. Expected: import errors for `reaction_molblocks`, then 404s.

- [ ] **Step 2: Implement.** Append to `ord_viewer/schemas.py`:

  ```python
  class AuthenticStandardMolblock(BaseModel):
      """A measurement's authentic standard."""

      molblock: str | None


  class MeasurementMolblocks(BaseModel):
      """The structures one product measurement names."""

      authentic_standard: AuthenticStandardMolblock


  class ProductMolblocks(BaseModel):
      """One product and its measurements' standards."""

      molblock: str | None
      measurements: list[MeasurementMolblocks]


  class OutcomeMolblocks(BaseModel):
      """One outcome's products."""

      products: list[ProductMolblocks]


  class ReactionMolblocks(BaseModel):
      """A molblock for every compound slot of a reaction; None where no structure reads."""

      inputs: dict[str, list[str | None]]
      outcomes: list[OutcomeMolblocks]
      workups: list[list[str | None]]


  class ReactionRecord(BaseModel):
      """One reaction as the editor returns it: the serialized proto and its molblocks."""

      reaction_id: str
      dataset_id: str | None
      # The base64 serialized Reaction, as the source file stores it.
      binpb: str
      molblocks: ReactionMolblocks
  ```

  Append to `ord_viewer/molblocks.py` (its imports gain
  `from ord_schema import message_helpers`, `from ord_schema.proto import reaction_pb2`,
  and the schema classes):

  ```python
  def _compound_molblock(
      compound: reaction_pb2.Compound | reaction_pb2.ProductCompound,
  ) -> str | None:
      """Return a compound's molblock, or None if none of its identifiers is a structure."""
      try:
          return message_helpers.molblock_from_compound(compound)
      except ValueError:
          return None


  def reaction_molblocks(reaction: reaction_pb2.Reaction) -> ReactionMolblocks:
      """Return a molblock for every input, product, standard, and workup compound."""
      return ReactionMolblocks(
          inputs={
              key: [_compound_molblock(component) for component in reaction_input.components]
              for key, reaction_input in reaction.inputs.items()
          },
          outcomes=[
              OutcomeMolblocks(
                  products=[
                      ProductMolblocks(
                          molblock=_compound_molblock(product),
                          measurements=[
                              MeasurementMolblocks(
                                  authentic_standard=AuthenticStandardMolblock(
                                      molblock=_compound_molblock(measurement.authentic_standard)
                                  )
                              )
                              for measurement in product.measurements
                          ],
                      )
                      for product in outcome.products
                  ]
              )
              for outcome in reaction.outcomes
          ],
          workups=[
              [_compound_molblock(component) for component in workup.input.components]
              for workup in reaction.workups
          ],
      )
  ```

  `ord_viewer/routes/reactions.py`:

  ```python
  """Reactions by ID, each with the molblocks the browser draws."""

  import base64
  from collections.abc import Sequence
  from typing import Annotated

  from fastapi import APIRouter, Depends, HTTPException, Query, status
  from ord_schema.proto import reaction_pb2
  from ord_schema.search import execute

  from ord_viewer.molblocks import reaction_molblocks
  from ord_viewer.schemas import ReactionRecord
  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api/reactions")

  # One page of result cards. 100 IDs are about 4 KiB of query string.
  _MAX_IDS = 100


  def fetch_records(
      corpus: execute.Corpus, reaction_ids: Sequence[str]
  ) -> list[ReactionRecord]:
      """Fetch reactions by ID, once each, in the order first asked; unknown IDs are skipped."""
      records = []
      for row in corpus.reactions(reaction_ids).to_pylist():
          blob = row["reaction"]
          records.append(
              ReactionRecord(
                  reaction_id=row["reaction_id"],
                  dataset_id=row["dataset_id"],
                  binpb=base64.b64encode(blob).decode(),
                  molblocks=reaction_molblocks(reaction_pb2.Reaction.FromString(blob)),
              )
          )
      return records


  @router.get("")
  def list_reactions(
      state: Annotated[ViewerState, Depends(get_state)],
      reaction_ids: Annotated[list[str], Query(alias="id")],
  ) -> list[ReactionRecord]:
      """Return up to 100 reactions, named by repeated id parameters."""
      if len(reaction_ids) > _MAX_IDS:
          raise HTTPException(
              status.HTTP_422_UNPROCESSABLE_ENTITY,
              f"asked for {len(reaction_ids)} reactions; ask for at most {_MAX_IDS}",
          )
      return fetch_records(state.corpus, reaction_ids)


  @router.get("/{reaction_id}")
  def get_reaction(
      reaction_id: str, state: Annotated[ViewerState, Depends(get_state)]
  ) -> ReactionRecord:
      """Return one reaction."""
      records = fetch_records(state.corpus, [reaction_id])
      if not records:
          raise HTTPException(status.HTTP_404_NOT_FOUND, f"no reaction {reaction_id}")
      return records[0]
  ```

  Register `reactions.router` in `main.py`.

- [ ] **Step 3: Run.** `uv run --frozen pytest -n auto -q`. Expected: `19 passed`.
- [ ] **Step 4: Lint and commit** ("Serve reactions with their molblocks"). Then run
  `frontend/node_modules/.bin/jscpd --config .jscpd.json` from the repository root: if it
  matches `molblocks.py` against the editor's `get_molblocks`, say so in the PR rather
  than adding an ignore entry; the two follow different ord-schema versions.

### Task V2.3: Downloads

**Files:**

- Modify: `ord_viewer/schemas.py`, `ord_viewer/main.py`
- Create: `ord_viewer/routes/download.py`
- Test: `ord_viewer/routes/download_test.py`

**Interfaces:**

- Produces: `ord_viewer.schemas.DownloadRequest(reaction_ids: list[str])`, 1 to 1,000 IDs.

- [ ] **Step 1: Failing tests.** `ord_viewer/routes/download_test.py`:

  ```python
  import gzip

  from ord_schema.proto import dataset_pb2


  def test_downloads_a_gzipped_dataset(client):
      response = client.post(
          "/api/download", json={"reaction_ids": ["ord-viewer0101", "ord-viewer0201", "ord-unknown"]}
      )
      assert response.status_code == 200
      assert response.headers["content-type"] == "application/gzip"
      assert 'filename="ord-search-results.pb.gz"' in response.headers["content-disposition"]
      dataset = dataset_pb2.Dataset.FromString(gzip.decompress(response.content))
      assert [reaction.reaction_id for reaction in dataset.reactions] == ["ord-viewer0101", "ord-viewer0201"]


  def test_nothing_known_is_not_found(client):
      assert client.post("/api/download", json={"reaction_ids": ["ord-unknown"]}).status_code == 404


  def test_bounds_the_request(client):
      assert client.post("/api/download", json={"reaction_ids": []}).status_code == 422
      too_many = [f"ord-{index}" for index in range(1001)]
      assert client.post("/api/download", json={"reaction_ids": too_many}).status_code == 422
  ```

- [ ] **Step 2: Implement.** `schemas.py` gains (with `from pydantic import Field`):

  ```python
  class DownloadRequest(BaseModel):
      """The reactions to download: at most one search's worth."""

      reaction_ids: list[str] = Field(min_length=1, max_length=1000)
  ```

  `ord_viewer/routes/download.py`:

  ```python
  """Reactions as a gzipped ord.Dataset, for a search's results or a selection."""

  import gzip
  from typing import Annotated

  from fastapi import APIRouter, Depends, HTTPException, Response, status
  from ord_schema.proto import dataset_pb2, reaction_pb2

  from ord_viewer.schemas import DownloadRequest
  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api")


  @router.post("/download")
  def download(
      body: DownloadRequest, state: Annotated[ViewerState, Depends(get_state)]
  ) -> Response:
      """Return the known reactions among the IDs as one gzipped Dataset."""
      table = state.corpus.reactions(body.reaction_ids)
      if table.num_rows == 0:
          raise HTTPException(
              status.HTTP_404_NOT_FOUND, "none of these reactions are in the corpus"
          )
      dataset = dataset_pb2.Dataset(
          name="ORD search results",
          description=f"{table.num_rows} reactions from the Open Reaction Database",
          reactions=[
              reaction_pb2.Reaction.FromString(blob)
              for blob in table.column("reaction").to_pylist()
          ],
      )
      return Response(
          content=gzip.compress(dataset.SerializeToString()),
          media_type="application/gzip",
          headers={"Content-Disposition": 'attachment; filename="ord-search-results.pb.gz"'},
      )
  ```

  Register `download.router` in `main.py`.

- [ ] **Step 3: Run.** Expected: `22 passed`.
- [ ] **Step 4: Lint, commit** ("Serve downloads as gzipped datasets"), push, and open PR
  V2, "Serve the viewer's datasets, reactions, and downloads". Body: the five routes, the
  molblock shape and its source in the editor, the 404s and limits. Check CI once; work
  Greptile and SonarCloud with `review-pr`.

---

## PR V3: search

Branch `viewer-backend-search`, in its own worktree from `origin/main` after V2 merges.

### Task V3.1: A cap on searches in flight

**Files:**

- Create: `ord_viewer/slots.py`
- Modify: `ord_viewer/settings.py`, `ord_viewer/state.py`, `ord_viewer/main.py`,
  `ord_viewer/searching.py`
- Test: `ord_viewer/slots_test.py`, `ord_viewer/routes/datasets_test.py`

**Interfaces:**

- Produces:
  - `Settings.slot_wait_seconds: float` (> 0, default 10).
  - `ord_viewer.slots.SearchSlots(capacity: int, wait_seconds: float)` with
    `hold() -> contextlib.AbstractContextManager[None]`, and
    `ord_viewer.slots.SlotsBusyError`, which the app answers with 503.
  - `ViewerState.slots: SearchSlots`. `run_search` holds a slot for the length of the
    search, so every route that searches waits for one.

- [ ] **Step 1: Failing tests.** `ord_viewer/slots_test.py`:

  ```python
  import pytest

  from ord_viewer.slots import SearchSlots, SlotsBusyError


  def test_waits_then_refuses_when_full():
      slots = SearchSlots(capacity=1, wait_seconds=0.01)
      with slots.hold(), pytest.raises(SlotsBusyError), slots.hold():
          pass


  def test_frees_a_slot_when_the_body_raises():
      slots = SearchSlots(capacity=1, wait_seconds=0.01)
      with pytest.raises(RuntimeError), slots.hold():
          raise RuntimeError("search failed")
      with slots.hold():
          pass
  ```

  Append to `ord_viewer/routes/datasets_test.py` (with `from ord_viewer.testing import make_client`):

  ```python
  def test_the_compound_counts_wait_for_a_search_slot(corpus_dir):
      with make_client(corpus_dir, max_concurrent=1, slot_wait_seconds=0.05) as client:
          with client.app.state.viewer.slots.hold():
              response = client.get("/api/datasets/ord_dataset-viewer01/compounds")
          assert response.status_code == 503
          assert client.get("/api/datasets/ord_dataset-viewer01/compounds").status_code == 200
  ```

- [ ] **Step 2: Implement.** `ord_viewer/slots.py`:

  ```python
  """A cap on searches in flight, since each one can hold the corpus's CPUs."""

  import contextlib
  import threading
  from collections.abc import Iterator


  class SlotsBusyError(Exception):
      """Every slot stayed taken for as long as a request may wait."""


  class SearchSlots:
      """A bounded number of concurrent searches; a request waits a while for one."""

      def __init__(self, capacity: int, wait_seconds: float) -> None:
          self._semaphore = threading.BoundedSemaphore(capacity)
          self._wait_seconds = wait_seconds

      @contextlib.contextmanager
      def hold(self) -> Iterator[None]:
          """Hold one slot for the body of the with statement.

          Raises:
              SlotsBusyError: If no slot frees within the wait.
          """
          if not self._semaphore.acquire(timeout=self._wait_seconds):
              raise SlotsBusyError(
                  f"every search slot stayed busy for {self._wait_seconds} s; try again"
              )
          try:
              yield
          finally:
              self._semaphore.release()
  ```

  `Settings` gains

  ```python
      # How long a request waits for a free search slot before answering 503.
      slot_wait_seconds: float = Field(default=10.0, gt=0)
  ```

  `ViewerState` gains `slots: SearchSlots`. In `main.py`'s lifespan:

  ```python
          app.state.viewer = ViewerState(
              settings=settings,
              corpus=corpus,
              slots=SearchSlots(settings.max_concurrent, settings.slot_wait_seconds),
          )
  ```

  and after building the app (with `from fastapi import Request` and
  `from fastapi.responses import JSONResponse`):

  ```python
      app.add_exception_handler(SlotsBusyError, _slots_busy)
  ```

  where, at module level:

  ```python
  async def _slots_busy(request: Request, error: Exception) -> JSONResponse:
      """Answer 503 when every search slot stayed busy."""
      return JSONResponse(status_code=503, content={"detail": str(error)})
  ```

  In `searching.py`, `run_search` holds a slot outside the error mapping:

  ```python
      with state.slots.hold(), search_errors():
          return state.corpus.search(
              request, timeout_seconds=state.settings.search_timeout_seconds
          )
  ```

- [ ] **Step 3: Run.** Expected: `25 passed`.
- [ ] **Step 4: Lint and commit** ("Cap the searches in flight").

### Task V3.2: `POST /api/search`

**Files:**

- Modify: `ord_viewer/schemas.py`, `ord_viewer/searching.py`, `ord_viewer/main.py`
- Create: `ord_viewer/routes/search.py`
- Test: `ord_viewer/searching_test.py`, `ord_viewer/routes/search_test.py`

**Interfaces:**

- Produces:
  - `ord_viewer.schemas`: `SearchRequest(query: Query)`,
    `ReactionsResult(kind: Literal["reactions"], reaction_ids: list[str], truncated: bool)`,
    `TableResult(kind: Literal["table"], columns: list[str], rows: list[list[Any]], truncated: bool)`,
    and `SearchResult = Annotated[ReactionsResult | TableResult, Field(discriminator="kind")]`.
  - `ord_viewer.searching.to_result(request: Query, table: pa.Table) -> ReactionsResult | TableResult`.
    V4's `/api/ask` returns the same result.

- [ ] **Step 1: Failing tests.** `ord_viewer/searching_test.py`:

  ```python
  import pyarrow as pa
  from ord_schema.search import execute
  from ord_schema.search.query import Query

  from ord_viewer.searching import to_result


  def test_a_plain_query_gives_reaction_ids_and_reads_the_truncation_flag():
      table = pa.table({"reaction_id": ["ord-a", "ord-b"]}).replace_schema_metadata(
          {execute.TRUNCATED: b"true"}
      )
      result = to_result(Query.model_validate({"limit": 2}), table)
      assert result.kind == "reactions"
      assert result.reaction_ids == ["ord-a", "ord-b"]
      assert result.truncated


  def test_an_aggregate_gives_a_table():
      request = Query.model_validate(
          {"aggregate": {"group_by": ["dataset_id"], "measures": [{"fn": "count", "name": "reactions"}]}}
      )
      table = pa.table({"dataset_id": ["ord_dataset-x"], "reactions": [3]})
      result = to_result(request, table)
      assert result.kind == "table"
      assert result.columns == ["dataset_id", "reactions"]
      assert result.rows == [["ord_dataset-x", 3]]
      assert not result.truncated
  ```

  `ord_viewer/routes/search_test.py`:

  ```python
  import pytest

  from ord_viewer.testing import make_client

  _PYRIDINE_INPUT = {
      "op": "exists",
      "path": "inputs.components",
      "where": {"op": "substructure", "path": "smiles", "smarts": "c1ccncc1"},
  }


  def _ids(client, query):
      response = client.post("/api/search", json={"query": query})
      assert response.status_code == 200, response.text
      body = response.json()
      assert body["kind"] == "reactions"
      return set(body["reaction_ids"])


  def test_substructure(client):
      assert _ids(client, {"where": _PYRIDINE_INPUT}) == {"ord-viewer0101"}


  def test_a_compound_by_name(client):
      query = {"where": {**_PYRIDINE_INPUT, "where": {"op": "substructure", "path": "smiles", "compound": "pyridine"}}}
      assert _ids(client, query) == {"ord-viewer0101"}


  def test_an_unknown_name_is_unprocessable(client):
      query = {"where": {**_PYRIDINE_INPUT, "where": {"op": "substructure", "path": "smiles", "compound": "unobtainium"}}}
      response = client.post("/api/search", json={"query": query})
      assert response.status_code == 422
      assert "unobtainium" in response.json()["detail"]


  @pytest.mark.parametrize(
      ("chirality", "expected"),
      [(True, {"ord-viewer0102"}), (False, {"ord-viewer0102", "ord-viewer0201"})],
  )
  def test_stereocenters_match_unless_told_not_to(client, chirality, expected):
      query = {
          "where": {
              "op": "exists",
              "path": "inputs.components",
              "where": {"op": "substructure", "path": "smiles", "smarts": "C[C@@H](N)C(=O)O", "chirality": chirality},
          }
      }
      assert _ids(client, query) == expected


  def test_a_yield_range(client):
      query = {
          "where": {
              "op": "exists",
              "path": "outcomes.products",
              "where": {
                  "op": "exists",
                  "path": "measurements",
                  "where": {
                      "op": "and",
                      "clauses": [
                          {"op": "eq", "path": "type", "value": {"literal": "YIELD"}},
                          {"op": "ge", "path": "percentage.value", "value": {"literal": 60}},
                          {"op": "le", "path": "percentage.value", "value": {"literal": 70}},
                      ],
                  },
              },
          }
      }
      assert _ids(client, query) == {"ord-viewer0101"}


  def test_a_dataset(client):
      query = {"where": {"op": "eq", "path": "dataset_id", "value": {"literal": "ord_dataset-viewer02"}}}
      assert _ids(client, query) == {"ord-viewer0201", "ord-viewer0202"}


  def test_a_reaction_smarts(client):
      query = {"where": {"op": "reaction_smarts", "smarts": "cB(O)O.c[Br,I]>>c-c"}}
      assert _ids(client, query) == {"ord-viewer0101"}


  def test_no_match_is_an_empty_answer(client):
      query = {"where": {**_PYRIDINE_INPUT, "where": {"op": "substructure", "path": "smiles", "smarts": "[Xe]"}}}
      response = client.post("/api/search", json={"query": query})
      assert response.json() == {"kind": "reactions", "reaction_ids": [], "truncated": False}


  def test_an_aggregate_is_a_table(client):
      query = {"aggregate": {"group_by": ["dataset_id"], "measures": [{"fn": "count", "name": "reactions"}]}}
      body = client.post("/api/search", json={"query": query}).json()
      assert body["kind"] == "table"
      assert body["columns"] == ["dataset_id", "reactions"]
      assert sorted(body["rows"]) == [["ord_dataset-viewer01", 3], ["ord_dataset-viewer02", 2]]


  def test_bad_queries_are_unprocessable(client):
      unknown_path = {"where": {"op": "eq", "path": "no_such_field", "value": {"literal": 1}}}
      assert client.post("/api/search", json={"query": unknown_path}).status_code == 422
      extra_key = {"where": _PYRIDINE_INPUT, "page": 2}
      assert client.post("/api/search", json={"query": extra_key}).status_code == 422


  def test_a_search_past_its_timeout(corpus_dir):
      with make_client(corpus_dir, search_timeout_seconds=1e-9) as client:
          response = client.post("/api/search", json={"query": {"where": _PYRIDINE_INPUT}})
      assert response.status_code == 504


  def test_a_failed_search_frees_its_slot(corpus_dir):
      with make_client(corpus_dir, max_concurrent=1, slot_wait_seconds=0.05) as client:
          bad = {"where": {"op": "eq", "path": "no_such_field", "value": {"literal": 1}}}
          assert client.post("/api/search", json={"query": bad}).status_code == 422
          assert client.post("/api/search", json={"query": {"where": _PYRIDINE_INPUT}}).status_code == 200
          with client.app.state.viewer.slots.hold():
              busy = client.post("/api/search", json={"query": {"where": _PYRIDINE_INPUT}})
          assert busy.status_code == 503
  ```

- [ ] **Step 2: Implement.** Append to `ord_viewer/schemas.py` (imports gain `Annotated`,
  `Any`, `Literal` from `typing`, `Field` from pydantic, and
  `from ord_schema.search.query import Query`):

  ```python
  class SearchRequest(BaseModel):
      """One query in the search grammar, as the form and /ask both produce."""

      query: Query


  class ReactionsResult(BaseModel):
      """A plain query's answer: reaction IDs to fetch a page at a time."""

      kind: Literal["reactions"] = "reactions"
      reaction_ids: list[str]
      # True when the corpus's 1,000-row bound may have cut the answer.
      truncated: bool


  class TableResult(BaseModel):
      """An aggregate's answer: its group and measure columns."""

      kind: Literal["table"] = "table"
      columns: list[str]
      rows: list[list[Any]]
      truncated: bool


  SearchResult = Annotated[ReactionsResult | TableResult, Field(discriminator="kind")]
  ```

  Append to `ord_viewer/searching.py` (imports gain the two result classes):

  ```python
  def to_result(request: Query, table: pa.Table) -> ReactionsResult | TableResult:
      """Shape a search's table as the result the viewer reads.

      Args:
          request: The query that produced the table; an aggregate gives a table.
          table: What Corpus.search returned.

      Returns:
          Reaction IDs for a plain query, or the columns and rows of an aggregate, each
          saying whether the corpus's row bound may have cut it.
      """
      truncated = (table.schema.metadata or {}).get(execute.TRUNCATED.encode()) == b"true"
      if request.aggregate is None:
          return ReactionsResult(
              reaction_ids=table.column("reaction_id").to_pylist(), truncated=truncated
          )
      return TableResult(
          columns=table.column_names,
          rows=[list(row.values()) for row in table.to_pylist()],
          truncated=truncated,
      )
  ```

  `ord_viewer/routes/search.py`:

  ```python
  """Search in the grammar ord-schema's search compiles."""

  from typing import Annotated

  from fastapi import APIRouter, Depends

  from ord_viewer.schemas import SearchRequest, SearchResult
  from ord_viewer.searching import run_search, to_result
  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api")


  @router.post("/search")
  def search(
      body: SearchRequest, state: Annotated[ViewerState, Depends(get_state)]
  ) -> SearchResult:
      """Run one query: reaction IDs for a plain query, a table for an aggregate."""
      return to_result(body.query, run_search(state, body.query))
  ```

  Register `search.router` in `main.py`.

- [ ] **Step 3: Run.** Expected: `40 passed`. If `test_a_search_past_its_timeout`
  passes with 200, `Corpus.search` finished every phase before checking its deadline;
  raise the query's cost (a `chirality: false` substructure over every input) rather than
  loosening the assertion.
- [ ] **Step 4: Lint and commit** ("Search the corpus in the query grammar").

### Task V3.3: Cache resolved compound names

**Files:** `ord_viewer/corpus.py`; test `ord_viewer/corpus_test.py`

**Interfaces:**

- Produces: `resolve_compound_name` keeps its signature and gains
  `functools.lru_cache(maxsize=4096)`, so `resolve_compound_name.cache_clear()` exists.

- [ ] **Step 1: Failing test.** `ord_viewer/corpus_test.py`:

  ```python
  import pytest
  from ord_schema import resolvers

  from ord_viewer.corpus import resolve_compound_name


  def test_caches_names_that_resolve_and_retries_names_that_do_not(monkeypatch):
      asked = []

      def resolve_name(value_type, value):
          asked.append(value)
          if value == "pyridine":
              return "c1ccncc1", "test"
          raise ValueError(f"Could not resolve {value_type} {value} to SMILES")

      monkeypatch.setattr(resolvers, "resolve_name", resolve_name)
      resolve_compound_name.cache_clear()
      assert resolve_compound_name("pyridine") == "c1ccncc1"
      assert resolve_compound_name("pyridine") == "c1ccncc1"
      for _ in range(2):
          with pytest.raises(ValueError):
              resolve_compound_name("unobtainium")
      assert asked == ["pyridine", "unobtainium", "unobtainium"]
      resolve_compound_name.cache_clear()
  ```

  Expected: FAIL, `asked` holds `pyridine` twice (or `cache_clear` is missing).

- [ ] **Step 2: Implement.** In `corpus.py`, `import functools` and decorate:

  ```python
  # Resolutions reach PubChem, CACTUS, and OPSIN; a name that resolved once is kept for
  # the life of the process. A name that failed raises again, so it is retried.
  @functools.lru_cache(maxsize=4096)
  def resolve_compound_name(name: str) -> str:
  ```

- [ ] **Step 3: Run, lint, commit** ("Cache resolved compound names"). Expected: `41 passed`.

### Task V3.4: Timings against a full corpus

Not committed. The numbers go in PR V3's body.

- [ ] **Step 1: Derive a corpus with the viewer's own environment**, so its stamps match
  (about an hour; run it in a terminal tab). ord-data's files must be real Parquet, not
  LFS pointers: `git -C ~/ord/ord-data lfs ls-files | head -1` lists them with `*`.

  ```bash
  corpus=~/ord/viewer-corpus
  mkdir -p "$corpus" && cp -R ~/ord/ord-data/data "$corpus/sources"
  cd ~/ord/worktrees/ord-app/viewer-backend-search/backend/viewer
  uv run --frozen python -m ord_schema.artifacts.scripts.derive_projection --input_pattern="$corpus/sources/*/*.parquet" --output_dir="$corpus/projections"
  uv run --frozen python -m ord_schema.artifacts.scripts.derive_structures --input_pattern="$corpus/projections/*/*.parquet" --output_dir="$corpus/structures"
  uv run --frozen python -m ord_schema.artifacts.scripts.derive_pivots --input_pattern="$corpus/projections/*/*.parquet" --output_dir="$corpus/pivots"
  uv run --frozen python -m ord_schema.artifacts.scripts.derive_occurrences --pivots_dir="$corpus/pivots" --output_dir="$corpus/occurrences"
  uv run --frozen python -m ord_schema.search.check --projections="$corpus/projections/*/*.parquet" --structures="$corpus/structures/*/*.parquet" --sources="$corpus/sources/*/*.parquet" --pivots="$corpus/pivots"
  ```

  Expected: the check exits 0.

- [ ] **Step 2: Serve and time.**

  ```bash
  ORD_VIEWER_CORPUS_DIR="$corpus" ORD_VIEWER_MEMORY_LIMIT=6500MiB \
    uv run --frozen uvicorn ord_viewer.main:app --port 8001 2>&1 | tee "$TMPDIR/viewer.log" &
  # When the log says "Application startup complete":
  ps -o rss= -p "$(pgrep -f 'uvicorn ord_viewer.main:app')"
  timed() { curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" "$@"; }
  search() { timed -H 'content-type: application/json' -d "{\"query\": $1}" http://127.0.0.1:8001/api/search; }
  search '{"where": {"op": "exists", "path": "inputs.components", "where": {"op": "substructure", "path": "smiles", "smarts": "c1ccncc1"}}}'
  search '{"where": {"op": "reaction_smarts", "smarts": "C(=O)O.N>>C(=O)N"}}'
  search '{"where": {"op": "exists", "path": "outcomes.products.measurements", "where": {"op": "and", "clauses": [{"op": "eq", "path": "type", "value": {"literal": "YIELD"}}, {"op": "ge", "path": "percentage.value", "value": {"literal": 90}}]}}}'
  timed http://127.0.0.1:8001/api/datasets
  ```

  Ask each search twice (first and repeat), and time
  `/api/datasets/<the USPTO dataset's ID>/compounds`, a page of 100 IDs from the first
  search through `/api/reactions`, and a 1,000-ID `/api/download`. Record the startup
  time from the log, the resident memory, and each request's first and repeat times in
  the PR body. Stop the server.

- [ ] **Step 3: Push and open PR V3**, "Search the viewer's corpus". Body: the route, the
  result shapes, the error table with 503, the slot cap, the resolver cache, and the
  timings. Check CI once; work Greptile and SonarCloud with `review-pr`.

---

## PR V4: `/api/ask`

Branch `viewer-backend-ask`, in its own worktree from `origin/main` after V3 merges.

### Task V4.1: Questions in English

**Files:**

- Modify: `ord_viewer/settings.py`, `ord_viewer/state.py`, `ord_viewer/main.py`,
  `ord_viewer/testing.py`, `backend/viewer/pyproject.toml`
- Create: `ord_viewer/routes/ask.py`
- Test: `ord_viewer/routes/ask_test.py`

**Interfaces:**

- Consumes: `run_search`'s slot and `search_errors` (V3), `to_result` and `SearchResult`
  (V3.2).
- Produces:
  - `Settings.ask_model: str` (default `nl.DEFAULT_MODEL`) and
    `Settings.ask_log: Literal["none", "stdout"]` (default `"none"`).
  - `ViewerState.ask_client: anthropic.Anthropic | None`.
  - `create_app(..., ask_client_factory: Callable[[], anthropic.Anthropic | None] = ask_client_from_environment)`.
  - `ord_viewer.routes.ask.get_ask_client(state) -> anthropic.Anthropic`, a dependency
    tests override, and `ask_client_from_environment() -> anthropic.Anthropic | None`.
  - `testing.make_client(corpus_dir, *, ask_client=None, **settings)`.

- [ ] **Step 1: Dependency.** In `backend/viewer/pyproject.toml`, add
  `"anthropic>=0.120,<1",` (the route imports it), then `uv lock` and check
  `git diff uv.lock | grep -E '^[-+]version'` prints nothing.

- [ ] **Step 2: Failing tests.** `ord_viewer/routes/ask_test.py`:

  ```python
  import types

  import anthropic
  import httpx
  import pytest
  from anthropic.types import TextBlock, ToolUseBlock

  from ord_viewer.routes.ask import get_ask_client
  from ord_viewer.testing import make_client

  _PYRIDINE_QUERY = {
      "where": {
          "op": "exists",
          "path": "inputs.components",
          "where": {"op": "substructure", "path": "smiles", "smarts": "c1ccncc1"},
      }
  }


  class _StubClient:
      """Answers messages.create from a script: a query dict, answer text, a refusal, or an error."""

      def __init__(self, *responses):
          self._responses = list(responses)
          self.requests = []
          self.messages = self

      def create(self, **kwargs):
          self.requests.append(kwargs)
          payload = self._responses.pop(0)
          if isinstance(payload, Exception):
              raise payload
          usage = types.SimpleNamespace(
              input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0
          )
          if isinstance(payload, str):
              content = [TextBlock(type="text", text=payload)]
          elif "reason" in payload:
              content = [ToolUseBlock(type="tool_use", id="toolu_stub", name="cannot_answer", input=payload)]
          else:
              content = [ToolUseBlock(type="tool_use", id="toolu_stub", name="build_query", input=payload)]
          stop = "end_turn" if isinstance(payload, str) else "tool_use"
          return types.SimpleNamespace(content=content, usage=usage, stop_reason=stop)


  @pytest.fixture
  def ask_with(client):
      def install(*responses):
          stub = _StubClient(*responses)
          client.app.dependency_overrides[get_ask_client] = lambda: stub
          return stub

      yield install
      client.app.dependency_overrides.clear()


  def test_answers_a_question(client, ask_with):
      stub = ask_with(_PYRIDINE_QUERY, "One reaction uses a pyridine.")
      response = client.post("/api/ask", json={"question": "reactions with a pyridine"})
      assert response.status_code == 200, response.text
      body = response.json()
      assert body["text"] == "One reaction uses a pyridine."
      assert body["result"] == {"kind": "reactions", "reaction_ids": ["ord-viewer0101"], "truncated": False}
      assert body["query"]["where"]["path"] == "inputs.components"
      assert len(stub.requests) == 2


  @pytest.mark.parametrize("question", ["   ", "x" * 2001])
  def test_refuses_an_empty_or_long_question_before_asking(client, ask_with, question):
      stub = ask_with()
      assert client.post("/api/ask", json={"question": question}).status_code == 422
      assert stub.requests == []


  def test_an_unanswerable_question(client, ask_with):
      ask_with({"reason": "the corpus records no prices"})
      response = client.post("/api/ask", json={"question": "what does pyridine cost"})
      assert response.status_code == 422
      assert "prices" in response.json()["detail"]


  def test_a_rate_limited_model(client, ask_with):
      request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
      ask_with(anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request, json={"error": {}}), body=None))
      assert client.post("/api/ask", json={"question": "anything"}).status_code == 429


  def test_no_key_means_no_answers(client):
      assert client.post("/api/ask", json={"question": "anything"}).status_code == 503


  def test_logs_questions_to_stdout(corpus_dir, capfd):
      stub = _StubClient(_PYRIDINE_QUERY, "One reaction uses a pyridine.")
      with make_client(corpus_dir, ask_client=stub, ask_log="stdout") as client:
          assert client.post("/api/ask", json={"question": "reactions with a pyridine"}).status_code == 200
      assert "reactions with a pyridine" in capfd.readouterr().out
  ```

  Expected: import error for `ord_viewer.routes.ask`.

- [ ] **Step 3: Implement.** `Settings` gains (with `from typing import Literal` and
  `from ord_schema.search import nl`):

  ```python
      # The model /api/ask translates questions with.
      ask_model: str = nl.DEFAULT_MODEL
      # Where /api/ask records each question: nowhere, or one JSON line on stdout.
      ask_log: Literal["none", "stdout"] = "none"
  ```

  `ViewerState` gains `ask_client: anthropic.Anthropic | None`.

  `ord_viewer/routes/ask.py`:

  ```python
  """Questions in English, translated into the search grammar by ord-schema's nl.ask."""

  import os
  from typing import Annotated

  import anthropic
  from fastapi import APIRouter, Depends, HTTPException, status
  from ord_schema.search import nl, nl_log
  from ord_schema.search.query import Query
  from pydantic import BaseModel, StringConstraints

  from ord_viewer.schemas import SearchResult
  from ord_viewer.searching import search_errors, to_result
  from ord_viewer.state import ViewerState, get_state

  router = APIRouter(prefix="/api")

  # The bound on one question, the model calls and the search together.
  _ASK_TIMEOUT_SECONDS = 60.0

  _STATUS_BY_ERROR: dict[type[nl.NLQueryError], int] = {
      nl.ModelUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
      nl.ModelRateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
      nl.ModelRefusedError: status.HTTP_422_UNPROCESSABLE_ENTITY,
      nl.UnanswerableError: status.HTTP_422_UNPROCESSABLE_ENTITY,
      nl.MalformedQueryError: status.HTTP_502_BAD_GATEWAY,
  }


  class AskRequest(BaseModel):
      """A question in English."""

      question: Annotated[
          str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
      ]


  class AskResponse(BaseModel):
      """The query a question became, a sentence about what it found, and the result."""

      query: Query
      text: str
      result: SearchResult


  def ask_client_from_environment() -> anthropic.Anthropic | None:
      """Return a client when ord-schema's key variable or the SDK's is set, else None."""
      if os.environ.get(nl.API_KEY_VARIABLE) or os.environ.get("ANTHROPIC_API_KEY"):
          return nl.get_client()
      return None


  def get_ask_client(
      state: Annotated[ViewerState, Depends(get_state)],
  ) -> anthropic.Anthropic:
      """Return the model client, or answer 503 when no key is configured."""
      if state.ask_client is None:
          raise HTTPException(
              status.HTTP_503_SERVICE_UNAVAILABLE, "no Anthropic API key is configured"
          )
      return state.ask_client


  @router.post("/ask")
  def ask(
      body: AskRequest,
      state: Annotated[ViewerState, Depends(get_state)],
      client: Annotated[anthropic.Anthropic, Depends(get_ask_client)],
  ) -> AskResponse:
      """Translate a question into a query, run it, and describe what it found."""
      sink = nl_log.StdoutSink() if state.settings.ask_log == "stdout" else None
      with state.slots.hold(), search_errors():
          try:
              answer = nl.ask(
                  body.question,
                  state.corpus,
                  client=client,
                  model=state.settings.ask_model,
                  timeout_seconds=_ASK_TIMEOUT_SECONDS,
                  sink=sink,
                  source="ord-viewer",
              )
          except nl.NLQueryError as error:
              code = _STATUS_BY_ERROR.get(type(error), status.HTTP_502_BAD_GATEWAY)
              raise HTTPException(code, str(error)) from error
      return AskResponse(
          query=answer.query,
          text=answer.text,
          result=to_result(answer.query, answer.table),
      )
  ```

  In `main.py`: `create_app` gains
  `ask_client_factory: Callable[[], anthropic.Anthropic | None] = ask_client_from_environment`;
  the lifespan passes `ask_client=ask_client_factory()` to `ViewerState`; register
  `ask.router`. In `testing.py`, `make_client` becomes:

  ```python
  def make_client(
      corpus_dir: pathlib.Path, *, ask_client: Any = None, **settings: Any
  ) -> TestClient:
      """Return an unentered client over corpus_dir, with any settings overridden.

      Args:
          corpus_dir: A corpus derived by derive_corpus.
          ask_client: What /api/ask calls messages.create on: an anthropic.Anthropic, or
              a stub that scripts its responses. None answers 503, as with no key.
          **settings: Settings fields to override.
      """
      app = create_app(
          lambda: Settings(corpus_dir=corpus_dir, **settings),
          resolver=offline_resolver,
          ask_client_factory=lambda: ask_client,
      )
      return TestClient(app)
  ```

- [ ] **Step 4: Run.** Expected: `48 passed`. If `test_an_unanswerable_question` gets 200,
  check that ord-schema's refusal tool is still named `cannot_answer`
  (`nl.REFUSAL_TOOL["name"]`).

- [ ] **Step 5: Docs, lint, commit.** `CLAUDE.md`'s viewer bullet gains "`/api/ask` needs
  `ORD_ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY`) and answers 503 without one."
  Commit ("Answer questions in English with ord-schema's nl.ask").

- [ ] **Step 6: Timing, if the user has a key in their shell.** Serve the full corpus as
  in V3.4 and time three questions ("reactions with a pyridine solvent", "yields above
  90% in Suzuki couplings", "the ten most used solvents"). Without a key, say in the PR
  that the timings were not taken.

- [ ] **Step 7: Push and open PR V4**, "Answer questions in English in the viewer's
  backend". Body: the route, the error table for the model's failures, the stdout log
  setting, and the timings. Check CI once; work Greptile and SonarCloud with
  `review-pr`.

### Task V4.2: Close out the step

In the logbook entry, set `viewer-backend-design.md`'s and this plan's status to "done"
with the PRs (L1, L2, the ord-infrastructure PR, V1–V4), and the README's step 3 to done.
A logbook PR: push everything, confirm with `gh pr view <n> --json files`, then arm
auto-merge.

---

## Refinements to the design

These came from reading ord-schema 0.9.1 and ord-app while planning; the design file has
been updated to match.

- **`slot_wait_seconds` is a setting** (default 10, the design's fixed wait), so tests
  can shorten it.
- **The dataset charts' route takes a search slot.** It runs an aggregate, which costs
  what a search costs. V2 introduces the 422 and 504 mapping with it; V3 adds 503.
- **Missing records.** `/api/reactions` returns each known reaction once, in the order
  first asked, and `[]` when none is known; `/api/download` answers 404 when none is
  known; `/api/datasets/{id}/compounds` answers 404 for an unknown dataset. A source
  with no `dataset_id` is left out of `/api/datasets`, since no route can address it.
- **The result's kind follows the query** (an `aggregate` gives a table), not the
  columns that came back.
- **The resolver** is ord-schema's `resolvers.resolve_name("name", …)` behind
  `functools.lru_cache`. It raises `ValueError` for an unknown name, which is what
  ord-schema's question log reads as an unresolved compound; a failed name is retried.
- **The corpus layout** has one shard level under each tree (`projections/*/*.parquet`,
  and `sources/*/*.parquet` as in ord-data's `data/<shard>/`), the layout the derive
  scripts write.
- **`create_app` takes the settings factory, the resolver, and the model client
  factory**, so tests inject a corpus, an offline resolver, and a stub client;
  `app = create_app()` reads the environment in the lifespan.
- **L1 drops pre-commit from the editor's dev group**, since pre-commit runs through
  `uvx` once there is no project at the root; the Makefile loses `check-pytype` and fixes
  `python-formating`, which runs `ruff format` as well; `backend/editor/.dockerignore`
  covers the compose image's context, and the root `.dockerignore` keeps the backend's
  `.env`, its tests, and `testdata/` out of the production image.
- **L2 moves the root `.dockerignore` to `deploy/editor/Dockerfile.dockerignore`**, which
  BuildKit reads in its place, keeps L1's exclusions (their paths are relative to the
  context, which stays the repository root), and excludes `.git/` from the editor image's
  context.
