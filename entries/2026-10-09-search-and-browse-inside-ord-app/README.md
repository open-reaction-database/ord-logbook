# Search and browse inside ord-app

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; plan agreed, and step 2 is designed in
  [`assets/shared-frontend-design.md`](assets/shared-frontend-design.md)
- **Tags:** ord-interface, ord-app, frontend, design-system, mantine, code-reuse, deployment
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

ord-interface, the public search and browse site at the apex domain, and ord-app, the
Auth0-gated editor at `app.`, look and work differently: colors, page shell, how a
reaction is drawn in a result list and on its own page, and the frontend stack under
all of it. ord-app's design is the target. How should the two converge, and can they
share code rather than keep copies in sync?

[2026-07-11](../2026-07-11-ord-interface-ui-revamp/README.md) took the in-place route:
[ord-interface#210](https://github.com/open-reaction-database/ord-interface/pull/210)
rebuilt the SPA on ord-app's stack, with the theme and the reaction page ported as
copies marked "keep in sync until extracted to a shared package." It was closed
unmerged on 2026-10-09. This entry replaces that approach.

## Summary

**Build a new search and browse viewer inside ord-app, ship it as its own image, and
retire ord-interface.** The viewer and the editor use one copy of the theme, the page
shell, and the reaction display, and the search API moves into ord-app with them.

- **Restyling ord-interface in place is a rewrite either way.** The two frontends share
  no styling system, router, proto bindings, Ketcher packaging, or molecule drawing
  (§1). ord-interface#210 showed the port can be done, and that what it produces is a
  second copy to keep in sync.
- **One repository instead of a shared package repository.** A published package costs
  a version bump and a lockfile update in two repositories for every shared change.
  Inside ord-app, shared code is an import, and one PR can change the editor and the
  viewer together.
- **The hard part is ord-app's display layer, not where the code lives.** Most of
  ord-app's reaction display reads through Redux, on the editor's own reaction model
  (§2). Before a viewer can reuse it, it has to take its data from a source the viewer
  can supply.
- **Deployment barely changes.** Both apps already sit behind one load balancer under
  separate host rules, and Pulumi builds each from a sibling checkout and a Dockerfile
  path (§3). The interface stack can point at a second Dockerfile in ord-app.

Decided so far:

- The viewer ships as a separate image on the apex domain, deployable without touching
  the editor, and has no login.
- The search backend moves into ord-app as its own Python package, served only by the
  viewer's image. It is not merged into the editor's API, and ord-interface is not kept
  as a backend-only repository.
- The viewer keeps what ord-interface has today: browse, dataset pages with their
  charts, structure, SMARTS, and yield search, reaction detail, downloads, and `/ask`.
- Keeping today's URLs (`/id/:reactionId`, `/dataset/:datasetId`) working is a
  nice-to-have, not a requirement.
- The viewer's reaction page matches ord-app's view-only mode, including the read-only
  form drawer behind each section's View button.
- The shared code takes its data from a provider each app implements, Redux in the
  editor and a plain object in the viewer, rather than the viewer running the editor's
  store.
- The frontend becomes an npm workspace in `frontend/`, with `apps/editor`,
  `apps/viewer`, and one private shared package in `packages/ui`. Nothing is published
  yet, but the package is built so that publishing later is a small step.
- Molecules are drawn in the browser with Indigo in both apps, so the viewer's API
  returns molblocks rather than SVG.

## Method

A read-only survey of ord-interface at
[`1953940`](https://github.com/open-reaction-database/ord-interface/commit/1953940),
ord-app at [`6acaa91`](https://github.com/open-reaction-database/ord-app/commit/6acaa91),
and ord-infrastructure at `676a420`, plus the open protobuf-es PRs in both apps
([ord-interface#221](https://github.com/open-reaction-database/ord-interface/pull/221),
[ord-app#837](https://github.com/open-reaction-database/ord-app/pull/837)). Line counts
are source lines, excluding tests.

## Findings

### 1. The two frontends

| | ord-interface `app/` | ord-app `ui/` |
| --- | --- | --- |
| Styling | a global SCSS file per component; Bootstrap 5.1.3 from a CDN, for the navbar and About only | Mantine 7 theme plus SCSS CSS modules |
| Palette | Bootstrap's: links `#0d6efd`, background `#f8f9fa` | primary `#3c78d8`, background `#f8f8f8`, hover `#ff8d00`, secondary text `#637d92` |
| Routing and data | React Router 7, TanStack Query | wouter, Redux Toolkit with axios thunks |
| Proto bindings | `ord-schema` (google-protobuf) | `ord-schema-protobufjs` |
| Ketcher | 2.5.1 standalone bundle in an iframe | `ketcher-react` 3.15 |
| Molecule drawing | server: RDKit SVG and HTML tables from `/api/reaction_summary` and `/api/compound_svg` | browser: Indigo WASM in a worker, from molblocks the API returns |
| Tooling | Vite 7, TypeScript 5.8, eslint recommended sets, Vitest on jsdom | Vite 6, TypeScript 5.6, eslint with sonarjs, stylelint, Vitest on happy-dom with coverage floors, Playwright, jscpd |
| Size | 6.3k lines of TS/TSX, 2.9k of SCSS | 34.7k lines: display 4.6k, editing 10.3k, reaction model and converters 5.9k |

Both protobuf-es PRs move to the same Buf SDK,
`@buf/open-reaction-database_ord-schema.bufbuild_es`, so shared code can be written
against it.

### 2. ord-app's reaction display

- **List rows.** `ReactionCard` wraps `ReactionPreview`: input cards joined by "+", an
  arrow, then outcome cards with yield, conversion, and a "Desired" badge.
- **Reaction page.** A header with the same preview, then Inputs, Conditions, Setup,
  Notes, Observations, Workups, Outcomes, Identifiers, and Provenance
  (`ui/src/features/reactions/ReactionView/`). Each section is a summary. Its View or
  Edit button opens a drawer holding the full entity form, which is disabled when the
  dataset is view-only.
- **Coupling.** 18 of the 34 display components read `reactionId` from
  `reactionContext` and their data through
  `useSelector(selectReactionPartByPath(...))`, on the editor's `AppReaction` model
  rather than the proto. Molecule previews come from a Redux slice that the preview
  worker's middleware fills. Only the leaf helpers take plain props: `KeyValueDisplay`,
  `RequiredOptionalFields`, `DataField`, `ReactionComponentPreview`, and
  `renderValuePrecisionUnit`.

### 3. Deployment

- **One load balancer, three host rules** (`stacks/backend`): the apex goes to
  ord-interface (priority 100), `app.` to ord-app (200), and `app-staging.` to ord-app's
  staging stack (300). Nothing routes by path between the apps.
- **Builds come from sibling checkouts.** `make_web_service()` in
  `ord_infrastructure/shared.py` takes a build directory and a Dockerfile path, behind a
  gate that requires a clean `main`. Pointing the interface stack at ord-app changes
  those two paths.
- **Shared and separate resources.** Both apps use one Aurora cluster, with different
  databases (`app` for ord-app, `ord_20260702` for ord-interface). Valkey and the
  Anthropic key belong to ord-interface alone. Auth0 belongs to ord-app alone, and its
  callback URLs list only the `app.` and `app-staging.` origins.
- **API prefixes.** ord-interface's nginx proxies `/api/`, and ord-app's proxies
  `/api/v1/`. Separate images keep them apart.

## Conclusions / next steps

Five steps, each with its own design and PRs:

1. **Land protobuf-es in ord-app**
   ([ord-app#837](https://github.com/open-reaction-database/ord-app/pull/837)).
2. **Extract a shared frontend package in ord-app:** the theme, the page shell, and the
   reaction display and drawer, taking their data from a provider instead of the
   editor's store. The editor moves onto it first, so the refactor is proven before a
   viewer depends on it. Designed in
   [`assets/shared-frontend-design.md`](assets/shared-frontend-design.md).
3. **Bring the search backend into ord-app** as its own package.
4. **Build the viewer** on the shared layer, as a second image.
5. **Point the interface stack at the new image** and archive ord-interface.

Open questions:

- **What the moved backend runs on.**
  [2026-10-02](../2026-10-02-what-the-search-api-still-needs/README.md) and
  [2026-10-03](../2026-10-03-source-parquet-instead-of-the-orm/README.md) plan to
  replace ord-interface's Postgres search with `ord_schema.search` and DuckDB over the
  source files. If that is ready by step 3, the new package builds on it rather than
  porting the cartridge-backed code.
- **ord-interface's open PRs**, including the protobuf-es migration (#221), matter only
  for as long as ord-interface serves the apex domain.

## References

- [2026-07-11: ord-interface UI revamp](../2026-07-11-ord-interface-ui-revamp/README.md)
  and [ord-interface#210](https://github.com/open-reaction-database/ord-interface/pull/210)
  (closed)
- [ord-app#837](https://github.com/open-reaction-database/ord-app/pull/837) and
  [ord-interface#221](https://github.com/open-reaction-database/ord-interface/pull/221):
  protobuf-es in each app
- [2026-08-26: migrating the proto build to buf](../2026-08-26-migrating-the-proto-build-to-buf/README.md),
  which published the SDK both PRs use
- [2026-10-02: what the search API still needs](../2026-10-02-what-the-search-api-still-needs/README.md)
  and [2026-10-03: source Parquet instead of the ORM](../2026-10-03-source-parquet-instead-of-the-orm/README.md)
- ord-infrastructure: `stacks/backend/__main__.py`, `stacks/interface/__main__.py`,
  `stacks/app/__main__.py`, `ord_infrastructure/shared.py`
