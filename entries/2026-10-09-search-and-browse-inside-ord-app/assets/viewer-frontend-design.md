# The viewer in ord-app

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** done; F1–F3 planned in [`viewer-frontend-plan.md`](viewer-frontend-plan.md)
  and F4–F6 in [`viewer-frontend-plan-f4-f6.md`](viewer-frontend-plan-f4-f6.md), and all
  merged. Each plan's Refinements say where the work departed from this design's first
  draft, which has been updated to match.
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Step 4 of [the entry](../README.md)'s plan. Paths are in ord-app at
[`a8ad1c5`](https://github.com/open-reaction-database/ord-app/commit/a8ad1c5),
ord-interface at
[`1953940`](https://github.com/open-reaction-database/ord-interface/commit/1953940),
ord-schema at
[`0fe5e1b`](https://github.com/open-reaction-database/ord-schema/commit/0fe5e1b), and
ord-infrastructure at `676a420`, unless they say otherwise.

## Goal

Build the public search and browse viewer as a second app in ord-app, on the shared
package ([step 2](shared-frontend-design.md)) and the viewer's backend
([step 3](viewer-backend-design.md)), and ship it as its own image. When this step is
done:

- `frontend/apps/viewer` does everything ord-interface's SPA does: browse, dataset pages
  and their charts, structure, SMARTS, reaction SMARTS, and yield search, reaction
  detail, a selected set, downloads, About, and `/ask`, which stays unlisted and marked
  as in development;
- `deploy/viewer` builds one image holding the SPA, nginx, and `ord_viewer`, which reads
  a corpus mounted at run time;
- CI builds each app's image in its own job, and runs the viewer's unit tests, its
  end-to-end tests against the real backend, and a smoke test of its image;
- nothing is deployed, and the apex domain still serves ord-interface. That is step 5.

## Decisions

| Question | Decision | Rejected |
| --- | --- | --- |
| What the repository holds | Two independent apps that share code. Each has its own image, CI jobs, and deployment; shared code lives only in `frontend/packages/ui` | One CI job or image covering both apps |
| Layout | Unchanged: `frontend/apps/viewer`, `backend/viewer`, and `deploy/viewer`, beside the editor's | Top-level `editor/` and `viewer/`, each holding a frontend, a backend, and a deploy directory |
| How far the search form reaches | Parity with ord-interface's form, compiled to a `Query` in the browser; anything richer goes through `/ask` | A match mode per structure; a raw query editor; a query builder over the grammar |
| Drawing structures | The editor's Ketcher dialog moves into the shared package as `./ketcher`, and both apps load it lazily | A second dialog in the viewer; text fields only |
| Reading the API | TanStack Query over `fetch`, with types generated from the backend's committed OpenAPI document | Hand-written types; Redux Toolkit with RTK Query |
| URLs | The editor's style of path, with ord-interface's paths redirecting; `/search` keeps ord-interface's parameters | ord-interface's paths unchanged; the `Query` as JSON in the URL |
| What the dataset charts count | Occurrences, as ord-interface's `/input_stats` does with `COUNT(*)` over compound rows | Reactions |
| What CI runs | Unit tests, end-to-end tests, and an image build per app, every job on every PR | Unit tests only; images built first at deployment |

### Why the layout stays

The tooling roots are per language, not per app. The two frontends and `packages/ui`
share one npm workspace and one lockfile, and `frontend/` is that root; grouping by app
would put the workspace's `package.json`, `node_modules`, and lint configs at the
repository root beside the Python, or keep a JavaScript root that lists each app's
frontend. The shared package belongs to neither app, so it would still need a third
top-level directory, and the backends share nothing. The move would also be the third
repository-wide one in a week, after W1 and L1, with another paired ord-infrastructure
PR for the editor's Dockerfile path. The names already pair by app, so per-app CI loses
nothing. A third deployable, or separate owners per app, would reopen the question.

## Layout

```text
frontend/apps/viewer/
  package.json  index.html  vite.config.ts  tsconfig*.json  playwright.config.ts
  e2e/                  Playwright specs
  src/
    main.tsx            MantineProvider with the package's theme, Notifications,
                        QueryClientProvider, and the router
    routes.tsx          the routes, and redirects from ord-interface's paths
    routeParams.ts      a path parameter decoded past what wouter decodes
    api/
      schema.ts         generated from backend/viewer/openapi.json; committed
      types.ts          the schema's types under the names the pages use
      client.ts         fetch to typed JSON; a non-2xx response throws ApiError
      queryClient.ts    the cache, which never goes stale, and its retry rule
      hooks.ts          one TanStack Query hook per route
      download.ts       /api/download's file, saved under the server's name
    search/             the form's state, to and from URL parameters, its compiler,
                        the form, and the results' selection
    reaction/           a record to a snapshot, the read-only provider and its slots,
                        and the full record's JSON
    pages/              Datasets, Dataset, Reaction, ReactionSet, Search, Ask, About,
                        NotFound
    components/         ViewerPage, ReactionList, ReactionResults, ResultTable,
                        CompoundChart, LinkedText, ErrorNotice, DownloadButton,
                        CopyLinkButton, FullRecordButton, and paging
frontend/packages/ui/
  src/ketcher/          StructureDialog, moved from the editor
backend/viewer/
  openapi.json          the API's OpenAPI document, committed
deploy/viewer/          Dockerfile, Dockerfile.dockerignore, nginx.conf,
                        supervisord.conf, exit_on_failure.sh, start.sh,
                        smoke_test.sh
```

- **Stack.** React 19, Vite 6, Mantine 7, wouter, TanStack Query 5, and
  `@mantine/charts`, with the shared package compiled from source as the editor does.
- **Package rules carry over.** The app imports the package only through its `exports`,
  and ESLint bans Redux, react-redux, axios, and Auth0 in `apps/viewer` as it does in
  `packages/ui`.
- **Root files that serve one app move to it.** `docker-compose.yml`, the editor's
  development stack of Postgres, its API, and a migration job, moves to
  `backend/editor/`, beside the Dockerfile it builds and the directory it mounts; it is
  for development, so not `deploy/editor/`. It sets `name: ord-app`, so the compose
  project, and with it the `pgdata` volume, keeps the name it has at the root.
- **The Makefile goes.** Nothing in CI or `scripts/` calls it, and pre-commit runs every
  tool its targets do (ruff, ruff-format, `ty`, jscpd). It is a third list of the
  Python projects, after pre-commit and `check_python`, that each new project has to
  join.
- **`ruff.toml` moves to `backend/`**, beside the Python projects, as `frontend/` holds
  the JavaScript configuration. Its `src` becomes `["editor", "viewer"]`, which ruff
  resolves against the file's directory; run from the root, ruff still finds it for
  every file under `backend/`.
- **The page carries ord-interface's Google Analytics tag** (`G-REEDLYB0ZJ`), as the apex
  domain's pages do today.

## Data flow

- **Pages read through hooks.** Each hook wraps one route through `client.ts`. TanStack
  Query caches by key, so going back to a result list does not fetch it again.
- **A reaction record becomes a provider.** A record's `binpb` and `molblocks` go through
  `ordBinpbToReaction` and `getReactionPreviews` from `reaction/model` to a snapshot,
  then `createStaticReactionSource`, then `ReactionProvider` with no `actions`, which
  makes the view read-only. The slots are `ReactionViewButton`,
  `DatasetReactionValueLabel` for both value labels, and a `ReactionLink` to
  `/reactions/:id`. There is no `MoleculeEditor`, so the drawer offers no drawing.
- **The snapshot's summary is empty.** `ReactionCard` renders nothing without a
  `summary`, and reads its contents only for the details `showDetails` turns on. The
  viewer's API returns none (the editor's backend returns a placeholder), so the viewer
  passes `{provenance: {}, summary: {}, conditions: ''}` and leaves the details off.
- **A search** goes from the URL's parameters to the form's state, through the compiler
  to a `Query`, to `POST /api/search`. The compiled query, like the dataset page's
  sample, orders by `reaction_id`, since the backend returns matches in no fixed order;
  ranking a similarity search by score, as ord-interface did, is not in the grammar. A
  `reactions` result is shown as cards, ten to a
  page by default and up to 100, each page fetched with one
  `GET /api/reactions?id=…`. A `table` result, which only `/ask` produces, is shown as a
  table.

### Types

`backend/viewer/openapi.json` is committed, and a pytest asserts that it equals
`create_app().openapi()`, printing the command that rewrites it. `npm run generate:api
-w apps/viewer` writes `src/api/schema.ts` from it with `openapi-typescript`, and
`lint_and_build_ui` regenerates it and fails on a diff. The generated file's license
header is addlicense's, stamped when the file is first committed; the generator keeps the
header the committed file starts with, so regenerating in a later year changes nothing.
ESLint, jscpd, and SonarCloud (through `.sonarcloud.properties`) skip the file. It is
generated with `defaultNonNullable: false`, so a field the backend defaults stays
optional unless the schema lists it as required, and a request may leave it out.

The backend's models and the viewer's types then cannot drift apart unnoticed, and the
Node job needs no Python. The grammar's predicates arrive as a discriminated union on
`op`, so `tsc` checks what the form compiles against the grammar's own types. A spike
against V3's backend generated 1,129 lines from its 35 schemas this way.

## Pages

| Route | Shows |
| --- | --- |
| `/` | The datasets as a table: the name, linked; the description, clamped, with the rest in a modal; the reaction count; and the ID. A filter box and paging work in the browser, as in ord-interface. |
| `/datasets/:id` | The dataset's name, ID, description, and reaction count. Two bar charts of the 30 most frequent inputs and products, from `/compounds`; hovering a bar draws its molecule from the molblock, with the SMILES and count; each chart renders its molecules together when it loads. Then up to 100 of the dataset's reactions, from `{where: dataset_id eq …, limit: 100}`, as paged cards with Download and Copy link, titled as a sample when the dataset holds more. |
| `/reactions/:id` | The editor's view-only page: breadcrumbs through the dataset, `ReactionHeader`, the Tabs and List switch, `ReactionContent`, and the drawer. The header adds Download, the reaction as `.pb.gz`, and Full record, the reaction as ord-schema's protobuf JSON in a modal, as ord-interface shows it. |
| `/search` | The form in a collapsible side panel, and the results beside it, or below it on a phone. Hiding the form keeps its unsent edits. |
| `/reactions?id=…` | A selected set of at most 100 reactions: paged cards, Download, and Copy link. |
| `/ask?q=…` | A note saying the feature is in development, a question box with ord-interface's three examples, then the answer's sentence, the `Query` it compiled to as collapsed JSON, and the result. |
| `/about` | ord-interface's About page, in the theme's type. |
| anything else | NotFound, as for an unknown dataset or reaction |

- **Navigation.** `PageContainer`'s header holds Browse, Search, Contribute (the
  editor), Docs, and About: in a row from Mantine's `sm` breakpoint up, and below it in
  a menu behind a button, since five links in a row overflow the 40 px header on a
  phone. `/ask` is not in it.
- **Redirects.** `/browse` goes to `/`, `/dataset/:id` to `/datasets/:id`, `/id/:id` to
  `/reactions/:id`, and `/selected-set?reaction_id=…` to `/reactions?id=…`, in the
  router. `/search` keeps ord-interface's parameters, so its shared links work as they
  are. nginx keeps ord-interface's 301 from `/editor` to the editor.
- **Path parameters.** wouter matches routes against the path after `decodeURI`, which
  leaves the escapes of reserved characters such as `/` in a parameter, so pages read
  `:id` through `routeParam`, which decodes the rest, and links encode an ID once.
- **The selected set holds at most 100 reactions**, one batch request, which keeps its URL
  near 4 KiB, inside nginx's default 8 KiB request line. Past 100, the result list's
  checkboxes disable and say why.

### The search form

| Field | Compiles to |
| --- | --- |
| An input structure | `{op: "exists", path: "inputs.components", where: …}` around the predicate below, on `smiles` |
| A product structure | the same over `outcomes.products` |
| Exact | `same_compound` with `smiles` |
| Similar | `similarity` with `smiles` and the threshold, 0.5 by default |
| Substructure | `substructure`, with the SMILES as `smarts` |
| SMARTS | `substructure` with `smarts` |
| Stereochemistry | `chirality` on each `substructure` and on `reaction_smarts`; unchecked by default, as in ord-interface, and enabled only beside a substructure, a SMARTS, or a reaction SMARTS |
| Reaction SMARTS | `reaction_smarts` |
| Yield | `exists outcomes.products`, holding `exists measurements` where `type` is `YIELD` and `percentage.value` is within the range |
| Conversion | `exists outcomes` where `conversion.value` is within the range |
| Dataset IDs, DOIs, reaction IDs | an `or` of `eq` on `dataset_id`, `provenance.doi`, or `reaction_id` |
| Limit | `limit`, 100 by default and at most 1,000 |

- **Fields are joined by `and`.** An empty field, a blank value, and a range left at
  0–100 add nothing, and a blank bound is missing rather than 0. A form with nothing
  set does not search, since a `Query` with no `where` is every reaction in the corpus.
- **The URL holds the form**, under ord-interface's parameter names (`component`,
  `use_stereochemistry`, `similarity`, `dataset_id`, `doi`, `reaction_id`,
  `reaction_smarts`, `min_yield`, `max_yield`, `min_conversion`, `max_conversion`,
  `limit`). Its legacy `component=pattern;target;mode` values parse too.
  `use_stereochemistry` is written with any structure, as ord-interface's URLs were, and
  with a reaction SMARTS.
- **Structures are typed or drawn.** Each structure field opens `StructureDialog`, which
  returns SMILES, or SMARTS in SMARTS mode.
- **A help note**, plain text rather than an alert, says where answers differ from the
  old site: a reaction SMARTS with several templates on a side returns fewer reactions
  than the cartridge's `@>`
  ([2026-10-02](../../2026-10-02-reaction-smarts-without-the-cartridge/README.md)), and
  the dataset charts read the projections' SMILES.

### Results

- **Selection.** Each card has a checkbox, and View selected opens `/reactions?id=…`; it
  is a disabled button while nothing is selected. The selection is kept in
  `sessionStorage`, keyed by the search's URL, so it survives Back.
- **Truncation.** When `truncated` says the 1,000-row bound may have cut the answer, the
  results say so. A search that stops at its own limit says that too, with the advice
  its page gives: the search form's limit can be raised, and a question can ask for
  more.
- **Missing IDs.** The backend skips an ID it does not hold, so a list names the IDs
  that did not come back.
- **Downloads.** Download all sends every result's ID, at most 1,000, to
  `/api/download`.
- **Tables.** A table result's columns and rows render as they come, scrolling inside
  their own container, and a `reaction_id` column links to the reaction.

### `/ask`

The question box takes 1 to 2,000 characters after trimming, counted by code point, as
the backend counts them. The question goes in the URL as `?q=`, so an ask can be linked;
loading the link asks again, within the session's cache and nginx's per-client limit.
The box follows the URL's question, so Back shows the question asked. Asking the
question already shown asks it again only after a failure, so a 429 or 503 can be
retried, and an answer is not paid for twice. The in-development note is plain text,
like the search's help note.

### Errors

| Status | Shown |
| --- | --- |
| 404 | NotFound, for an unknown dataset or reaction |
| 422 | The server's reason: a query that does not compile, a compound that does not resolve, or a question the model declined |
| 429 | Too many questions; try again in a minute |
| 502 | The question could not be turned into a search |
| 503 | The service is busy, or `/ask` is unavailable; try again |
| 504 | The search took too long; narrow it |

Anything else shows the status and the server's detail. A 502 or 504 that nginx wrote
itself, with its own page rather than FastAPI's JSON, means the backend is starting, down,
or did not answer in time, and shows the 503's message. A list of validation errors
with no messages shows the status text.

## Shared package changes

- **`./ketcher`.** `src/ketcher/` holds `StructureDialog({opened, onClose, initial,
  format, onSave, children})`: Ketcher's canvas in a Mantine modal with Cancel and Save,
  returning the drawing as a molfile, SMILES, or SMARTS. `children` adds fields above the
  buttons. It is the editor's `ComponentsKetcherEditor`, moved and generalized; the
  editor's `MoleculeEditor` slot becomes a wrapper that adds its Details field.
- **Dependencies.** `ketcher-react`, `ketcher-standalone`, and `ketcher-core` become the
  package's dependencies, with `buffer`, and the root's overrides for them stay. ESLint
  allows Ketcher imports only in `src/ketcher/KetcherDialog.tsx`, as it allows wouter
  only inside `src/shell/`.
- **Loading.** The package loads Ketcher lazily, not each app. Apps import
  `StructureDialog` statically; it renders nothing until first opened, then loads
  `KetcherDialog` through `React.lazy` and keeps it mounted, so Ketcher is a chunk of its
  own, fetched when a dialog first opens. Only an app that imports `./ketcher` compiles
  it, so step 2's concern about every app compiling Ketcher does not arise. The editor
  imports Ketcher statically through its slot table today, so its first load shrinks
  too.
- **Polyfills.** Ketcher's modules read Node's `global` and `Buffer`. The loader installs
  them before it imports `KetcherDialog`, so a host needs none for Ketcher. A module
  imported only for its side effects would not do, since the package's `sideEffects`
  lists only stylesheets and a production build may drop it. The editor keeps its own
  copy in `main.tsx`, since csv-parse reads `Buffer` as it loads.
- **Each opening gets its own Ketcher.** The modal unmounts the canvas when it closes, so
  `KetcherDialog` forgets the instance on close and loads `initial` into the next one.
  A chunk that fails to load stays inside the dialog, which offers Close and Try again;
  a retry loads afresh, since a failed `React.lazy` keeps its rejection.
- **Host requirements.** The README's list gains what an app that imports `./ketcher`
  provides: `define: {'process.env': {}}` in its Vite config.
- **Nothing else changes.** The viewer uses `PageContainer` with its navigation in
  `headerActions`, `ReactionProvider`, `createStaticReactionSource`, `ReactionHeader`,
  `ReactionContent`, `ReactionDetailsSidebar`, `ReactionCard` with the selection
  checkbox in its `actions`, and `renderPreviews` for the charts' molecules.

## Image

`deploy/viewer/Dockerfile` builds for `linux/arm64`, the platform the web services run on
since ord-infrastructure#55.

1. **A Node stage** copies the workspace's manifests (the root `package.json`, the
   lockfile, `.npmrc`, and each workspace's `package.json`) and runs `npm ci`, a layer
   that stays cached until the lockfile changes. It then copies the sources and runs
   `npm run build -w apps/viewer`.
2. **A `python:3.12-slim` stage** installs nginx and supervisor, runs
   `uv sync --frozen --no-dev --no-build` from `backend/viewer`'s lockfile, cached until
   the lock changes, then copies `ord_viewer`, the SPA, and the configs. It runs as a
   non-root user and listens on 8080, the interface stack's container port.
   `supervisord` runs uvicorn with one worker on `127.0.0.1:8000`, and nginx. Neither
   restarts: when either exits, an event listener stops supervisord and with it the
   container, so a backend that cannot open its corpus fails the task where it can be
   seen, rather than leaving nginx answering 502. The container's command, `start.sh`,
   exits 0 only for a stop it was asked for that supervisord carried out cleanly; a
   program's exit is 1, and supervisord failing or stopping on its own keeps its code,
   or is 1.

The corpus is not in the image: `ORD_VIEWER_CORPUS_DIR` names a directory mounted at run
time, and step 5 decides where it comes from. The viewer's bundle needs no settings at
build time, unlike the editor's Auth0 arguments.

### nginx

- **`location ^~ /api/`** proxies to uvicorn. It comes ahead of every static rule, so
  none shadows `/api/openapi.json`. Its `proxy_read_timeout` is 60 s, past the 10 s slot
  wait and the 30 s search timeout.
- **`location = /api/ask`** adds `limit_req` keyed by the client's address, at 10 a
  minute with a burst of 5 and status 429, and a `proxy_read_timeout` of 150 s, past the
  10 s slot wait, three model calls (the query, its repair, and the answer) of one 30 s
  attempt each (ord-app#894), and the 30 s search.
- **The client's address.** Behind the load balancer, `$remote_addr` is the balancer's.
  `set_real_ip_from 10.0.0.0/8`, `real_ip_header X-Forwarded-For`, and
  `real_ip_recursive on` restore the client's, so the limit counts each client rather
  than each balancer node.
- **Bodies.** `client_max_body_size 128k`; a download of 1,000 IDs is about 40 KiB.
- **Static files.** `/assets/` is cached as immutable and `index.html` as `no-cache`, as
  ord-interface's nginx does, and every other path falls back to `index.html`. gzip
  covers JavaScript, CSS, JSON, and wasm. `/editor` answers 301 to the editor.

## CI

| | Editor | Viewer |
| --- | --- | --- |
| Python tests | `test_python` | `test_python_viewer` |
| UI unit tests | `test_ui`, with `packages/ui` | `test_ui_viewer` (new) |
| End to end | `test_e2e` | `test_e2e_viewer` (new) |
| Image | `build_editor_image` (new) | `build_viewer_image` (new) |

- **Shared jobs** are the checks whose configuration spans the repository:
  `check_python` (ruff, and `ty` per project), `lint_and_build_ui` (one ESLint,
  Prettier, and stylelint configuration, and `tsc -b` across the project references),
  `check_duplication`, and `check_license_headers`.
- **Every job runs on every PR**, as the repository's required jobs do today: a required
  check that never reports leaves the PR blocked, so none is filtered by path.
- **`test_ui` keeps its name** and keeps running the shared package's tests, since branch
  protection matches checks by name and a rename would drop the gate silently.
- **The image jobs** run on `ubuntu-24.04-arm`, which builds `linux/arm64` natively, free
  for a public repository. Buildx caches layers in the GitHub Actions cache
  (`type=gha`, `mode=max`), one scope per image, so a PR that touches neither lockfile
  rebuilds only the source layers.
  - `build_editor_image` builds `deploy/editor/Dockerfile` with placeholder Auth0
    arguments, which its Vite config requires.
  - `build_viewer_image` builds and loads the image, derives the fixture corpus with
    `python -m ord_viewer.testing <directory>`, runs the image with it mounted, and checks
    through nginx that `/api/health` answers 200, that `/` and `/reactions/<a fixture
    ID>` serve `index.html`, that `/api/openapi.json` is the API's document, that an
    `/assets/` file carries its cache header, that `/editor` answers 301, and that
    `POST /api/ask` answers 503 with no key set. Every request has a time limit, and
    the wait for the backend a three-minute deadline. It then checks that a requested
    stop exits 0, and that a corpus that cannot open stops the container with exit
    code 1.
  - Each image job stops after 30 minutes. The first runs took 3.2 min cold and 1.4 min
    cached for the viewer, and 3.8 and 3.3 min for the editor.
- **Required checks.** `test_ui_viewer`, `test_e2e_viewer`, `build_editor_image`, and
  `build_viewer_image` have to be added to the `main` ruleset by hand, as
  `test_python_viewer` was.

## Testing

- **Vitest in `apps/viewer`**, with its own configuration and coverage floors that start
  at the coverage measured when the app lands, as `packages/ui`'s did, and stand at 99%
  of lines, statements, and functions and 100% of branches.
  - The compiler, table-driven: each field to its `Query`, URL parameters to form state
    and back, ord-interface's legacy `component` values, and a range left at 0–100
    adding nothing.
  - The client: each status to its `ApiError` and message.
  - Pages against a mocked `fetch`, with fixtures typed by the generated schema, so `tsc`
    catches a fixture that drifts from the API. The reaction views use one committed
    record, `GET /api/reactions/{reaction_id}`'s response for a fixture reaction, since
    a `binpb` and its molblocks are impractical to write by hand.
- **`test_e2e_viewer`**, with Playwright:
  - The backend runs as `uvicorn --factory ord_viewer.testing:e2e_app`, over the derived
    fixture corpus named by `ORD_VIEWER_CORPUS_DIR`, with the offline resolver and a
    scripted model client, which answers the questions in `ASK_SCRIPTS` and declines
    any other.
  - The viewer is a production build served by `vite preview`, which proxies `/api`.
    Nothing forces the dev server, as the editor's sign-in bypass does.
  - The flows: browse to a dataset, its charts, and its cards; a reaction, with the
    drawer opening read-only and no edit controls; one search for each form field; a
    selection and its set; a download, checking the file's name and gzip header; an ask,
    with its sentence, query, and result; an old URL's redirect; and NotFound.
  - One search per form field is the check on what `tsc` cannot see: the types prove the
    `Query`'s shape, and only the backend proves that its paths and operators compile.
  - `toHaveScreenshot` captures of the reaction page and a result list, each of the
    1280×1080 viewport with the footer's year masked, against baselines made in CI's
    Linux container, as in step 2.
  - Each page at 375 px with full-length IDs and links, which must not scroll sideways
    or clip what they show (`e2e/narrow.spec.ts`).
- **Backend additions.** `openapi.json` and its test, `python -m ord_viewer.testing
  <directory>`, and the `e2e_app` factory.

## Migration

Each PR from an up-to-date `main`, green on its own:

| PR | Change |
| --- | --- |
| F1 | `StructureDialog` moves into `packages/ui/src/ketcher`, exported as `./ketcher`. The editor wraps it for its `MoleculeEditor` slot and loads it lazily; a Playwright check opens the dialog and saves a drawing. The editor behaves as it does today. |
| F2 | The `apps/viewer` scaffold: its configuration, `main.tsx`, `ViewerPage` and the navigation, About, NotFound, and the redirects; `openapi.json` and its test; `generate:api` and the check on its output; the client and hooks; and `test_ui_viewer`, with `test_ui` narrowed to the editor and the package. |
| F3 | `deploy/viewer`, `build_viewer_image` with its smoke test, `build_editor_image`, and `python -m ord_viewer.testing`, with `deploy/viewer` added to Dependabot's docker entry. `docker-compose.yml` moves to `backend/editor/`, and Dependabot's `docker-compose` entry, the README, CLAUDE.md, the UI testing skill, and `scripts/dev-e2e.sh` follow it; `ruff.toml` moves to `backend/`; the Makefile goes, and CLAUDE.md's `make duplication` becomes `uvx pre-commit run jscpd --all-files`. It comes early, so arm64, RDKit, and nginx problems surface before the pages accumulate. |
| F4 | Browse, the dataset pages and their charts, the reaction page, the selected set, Download, and Full record; the `e2e_app` factory and `test_e2e_viewer`. |
| F5 | Search: the form, the compiler, the URL's state, drawing, the results and their selection, table results, and the help note. |
| F6 | `/ask`: the page, the banner, and its end-to-end flow with the scripted client. |

F1 can land at any point before F5. F2 through F6 run in order.

## Risks

- **F1 changes the editor.** The dialog's move must keep the editor's drawing as it is;
  F1's Playwright check and the editor's existing drawer tests hold it there.
- **Substructure takes SMARTS.** A SMILES read as SMARTS matches what the cartridge's
  SMILES query did for most patterns, but not every one, such as a charged or
  explicit-hydrogen atom. The end-to-end searches pin the common cases.
- **The Actions cache is 10 GB a repository** and evicts what was least recently used.
  Two images' layers fit, but a miss rebuilds from scratch: minutes, not a failure.
- **Every change to a backend model regenerates `schema.ts`** in the same PR. That is the
  point, but it puts a generated file in those diffs.
- **The image starts slowly.** The backend accepts no connections for about 40 s while it
  opens the corpus, during which nginx serves the SPA and answers 502 for `/api/`, which
  the pages show as the service being unavailable. Step 5 sets the health check's grace
  period.
- **The fixture corpus is small.** The charts and paging run on a few reactions; how they
  behave over the full corpus is step 5's check.

## Step 5 inherits

- **The interface stack's contract:** `deploy/viewer/Dockerfile`, port 8080, the health
  check at `/api/health` with a grace period past startup, and the `ORD_VIEWER_*`
  settings with the corpus mounted at `ORD_VIEWER_CORPUS_DIR`.
- **The real-address rule** assumes the load balancer's addresses fall inside
  `10.0.0.0/8`, as the backend stack's VPC does.
- **Sizing and the corpus**, as [step 3](viewer-backend-design.md#step-5-inherits) left
  them.

## Not in this step

Deployment, sizing, and getting the corpus to the container (step 5); the CSV and
pbtxt downloads ord-interface lists as coming soon; paging past 1,000 results; a query
builder; publishing the shared package.
