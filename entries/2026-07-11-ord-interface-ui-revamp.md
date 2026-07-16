# ord-interface UI revamp: shared look-and-feel and stack with ord-app + landing page

- **Date:** 2026-07-11
- **Author:** Claude Code (Fable 5), for Steven Kearnes
- **Status:** draft — PR open:
  [ord-interface#210](https://github.com/open-reaction-database/ord-interface/pull/210)
- **Tags:** ord-interface, ord-app, frontend, design-system, mantine, landing-page, code-reuse

## Question

The ord-interface search/browse SPA (`ord-interface/app`) looked like a lightly-styled
Bootstrap app, while the new contribute/editor app (`ord-app/ui`) has a polished
Mantine-based design. Can we revamp ord-interface to share ord-app's look-and-feel
AND its stack (so shared code can be extracted later), and add a proper landing page
with dataset/news highlights — to help drive adoption?

## Summary

**Done** — committed on ord-interface branch `ui-revamp-shared-look` and opened as
[PR #210](https://github.com/open-reaction-database/ord-interface/pull/210). The SPA now runs on ord-app's stack — Mantine 7 with ord-app's
theme file ported verbatim, `ord-schema-protobufjs` bindings, wouter routing, axios,
`ketcher-react`/`ketcher-standalone` (replacing the frozen Ketcher 2.5.1 iframe
bundle), mantine-react-table via a port of ord-app's DataTable, Tabler icons, SCSS
modules — and has a new landing page with live stats, featured datasets, and a
curated news section. All views (browse, search, dataset, reaction, selected-set,
NL search, About) were rebuilt in the shared visual language. Bootstrap, jQuery,
DataTables, and Material Icons CDN dependencies are gone.

Verified end-to-end against the in-process test backend: all 8 routes render with
zero console errors; structured substructure search, dataset charts, reaction detail
(decode + server-rendered summaries + compound SVGs) all work. `tsc -b`, `vite
build`, eslint, and prettier are green.

## Method

1. Three parallel Explore-agent sweeps: ord-app design-system extraction,
   ord-interface frontend map, cross-repo reuse analysis; plus a fourth pass pulling
   exact ord-app implementation details (decode path, Ketcher editor, DataTable,
   axios, Buffer polyfill).
2. Single implementation pass on `ui-revamp-shared-look` (branched from
   origin/main @ 8cafe29).
3. Runtime verification: `ORD_INTERFACE_TESTING=TRUE uvicorn` test backend + redis +
   Vite dev server; Playwright screenshots of every route at 1440px, console-error
   capture.

## Findings

- **Stack alignment (the "pull out shared code later" enabler):**
  - Protobuf: `ord-schema` (google-protobuf, `.AsObject` shapes) →
    `ord-schema-protobufjs@^0.6.31` (same package/range as ord-app). Display
    components now type against `ord.I*` interfaces — the same currency as ord-app's
    converters. Decode mirrors ord-app's `parseReaction`
    (`ord.Reaction.decode(Buffer.from(binpb, 'base64'))`).
  - Theme: `app/src/styles/theme.ts` and the CSS custom properties in
    `app/src/index.scss` are line-for-line ports of ord-app's
    `ui/src/common/styling/theme.ts` + `ui/src/index.scss` (+ accent palette from
    `colors.module.scss`), marked "keep in sync until extracted to a shared package".
  - Direct component ports from ord-app: PaperButton (colored action tiles),
    Pagination, DataTable (mantine-react-table wrapper incl. the orange first-cell
    row-hover), NotFound page, notification wrapper, Ketcher editor modal.
  - Deliberate deviation: kept TanStack Query for server state instead of adopting
    Redux Toolkit — ord-app's Redux holds editor-document state this read-only app
    doesn't have, and props-based display components (not store-coupled ones) are the
    realistic sharing surface. Also kept D3 for the two dataset bar charts.
- **Landing page** (`/`): hero with ORD logo + tagline + natural-language search box
  that hands off to `/ask` (the LLM-backed query flow; verified end-to-end with
  Playwright), live stats from `/api/datasets`, three PaperButton tiles (Browse/Search/Contribute), featured
  datasets (curated via `src/data/homeContent.ts`, falls back to largest-by-size from
  the live API), news timeline (same data file; seeded with the JACS 2021 paper, the
  JCIM 2023 perspective, and the new contribute app), "Open by design" strip, and a
  citation card with copy button.
- **Bugs found/fixed along the way:**
  - protobufjs `.finish()` returns a view into a shared pool buffer; axios transmits
    the view's whole underlying ArrayBuffer → `/api/compound_svg` got garbage bytes
    (HTTP 500). Fixed by copying to an exact-size buffer in `encodeCompound`.
  - The old ConditionsView formatted `peakWavelength` with the Length unit enum —
    nanometer values would have been labeled with the wrong units. Added a proper
    `wavelengthStr` formatter.
  - Yield precision displayed raw float32→double drift ("± 4.800000190734863");
    now rounded (ord-app solves the same problem with
    `convertReactionFloatsToDoubles`).
- **Bundle:** Ketcher (standalone WASM struct service) is a lazy-loaded route-split
  chunk (~7 MB gzip) fetched only when the draw modal opens; main bundle ~360 KB gzip.
  The separate "download Ketcher into app/public/" install step is gone.
- **Reaction page = true ord-app port (commit 874ec26).** The reaction detail view
  was rebuilt as a faithful port of ord-app's read-only ReactionPage rather than a
  reskin: breadcrumbs, Download action, header card with the reaction scheme preview
  (input cards → arrow → outcome card with Desired badge/yield), Tabs/List toggle,
  and the nine ReactionView section components with ord-app's uppercase tabs,
  separated accordions, component grid, and KeyValueDisplay/RequiredOptionalFields
  primitives. Verified pixel-close against a live no-auth ord-app stack rendering
  the identical seeded reaction in viewer mode (screenshots in session scratch).
  Molecule images come from /api/compound_svg (RDKit) instead of ord-app's client
  Indigo previews. The ported primitives are annotated keep-in-sync copies —
  concrete inputs for the shared-package extraction.
- **Not interactively verified:** the Ketcher draw modal itself (heavy chunk;
  pattern ported verbatim from ord-app's ComponentsKetcherEditor), file downloads,
  clipboard copies (headless permissions). Worth a manual click-through.

## Conclusions / next steps

- Review [PR #210](https://github.com/open-reaction-database/ord-interface/pull/210).
  Manual click-through of the Ketcher modal, downloads, and selected-set flow
  recommended.
- The Dockerfile's SPA Ketcher-copy step and the README's manual download step were
  removed in the PR (the legacy Flask editor keeps its own bundle, untouched).
- Reuse follow-ups unlocked by this work:
  1. Extract the theme + tokens (now byte-identical between the two apps) into a
     shared package (e.g. `@open-reaction-database/ui-theme`).
  2. Extract `ord_interface/visualization` (Python) into a shared package — ord-app
     once vendored it byte-for-byte (stale `.pyc`s remain in
     `ord-app/ord_app/visualization/__pycache__`) and its
     `ReactionResponseSchema.summary` stub is the obvious consumer.
  3. With both apps on `ord-schema-protobufjs`, the formatting utils
     (`enumName`, amount/conditions/outcomes formatters) and eventually the reaction
     section viewers can be co-designed into a shared component library (ord-app
     side needs de-Redux-ing of the presentational layer).
  4. Consider Mantine notifications/theme version lockstep (both pin ^7.15.3) when
     bumping either app.

## References

- ord-interface branch: `ui-revamp-shared-look` (from origin/main 8cafe29).
- Design sources: `ord-app/ui/src/common/styling/theme.ts`, `ui/src/index.scss`,
  `PageContainer`, `PaperButton`, `DataTable`, `Pagination`,
  `ComponentsKetcherEditor`.
- ord-interface CLEANUP_PLAN.md — legacy Flask editor untouched (deletion Aug 2026).
- Citation seed data: JACS 2021 (10.1021/jacs.1c09820), JCIM 2023
  (10.1021/acs.jcim.3c00607).
