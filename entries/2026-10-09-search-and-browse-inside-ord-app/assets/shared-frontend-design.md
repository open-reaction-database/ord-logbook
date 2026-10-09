# A shared frontend package for ord-app

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** design agreed; W1, W2, and A planned in
  [`shared-frontend-plan.md`](shared-frontend-plan.md)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

Step 2 of [the entry](../README.md)'s plan. Paths are in ord-app at
[`6acaa91`](https://github.com/open-reaction-database/ord-app/commit/6acaa91) unless
they say otherwise, and `ui/src/` is abbreviated to `src/`.

## Goal

Make ord-app's theme, page shell, and reaction display — including the read-only form
drawer — usable by a second app, the public search and browse viewer (step 4), without
copies. When this step is done:

- the frontend is an npm workspace under `frontend/`, with the editor in
  `frontend/apps/editor/` and the shared code in `frontend/packages/ui/`;
- nothing in `packages/ui` depends on Redux, react-redux, axios, Auth0, or the editor's
  routes, and the build and lint fail if something does;
- the editor runs on the package and behaves as it does today, except that read-only
  drawers no longer show a Delete icon;
- no viewer exists yet. This step only makes one possible.

## Decisions

| Question | Decision | Rejected |
| --- | --- | --- |
| How the viewer's reaction page looks | The same as ord-app's view-only mode: section summaries, and a read-only form drawer behind each View button | Summaries plus raw JSON; a generic field list built from the schema |
| How shared code gets its data | A provider that each app implements: Redux in the editor, a plain object in the viewer | The viewer runs the editor's Redux store; new components written against protobuf-es |
| Repository layout | npm workspaces in `frontend/`, with `apps/` and `packages/` | One `ui/` package with a lint-enforced shared directory; a separate repository |
| Publishing | Not now. The package is private, but built so that publishing later needs only a library build, `"private": false`, and Changesets | Publishing and versioning from the start |

The editor keeps Redux for what it is good at — the document being edited, with
optimistic updates and rollback. The shared code just doesn't reach it directly.

## Layout

```text
frontend/
  package.json            workspace root, private; workspaces apps/* and packages/*
  package-lock.json       the only lockfile
  .npmrc                  @buf registry, from ord-app#837
  tsconfig.base.json      compiler options every project extends
  eslint.config.mjs       one flat config, with blocks per workspace
  .prettierrc.json  .prettierignore  .stylelintrc.json  .stylelintignore
  apps/
    editor/               today's ui/: src/, public/, e2e/, index.html, vite and
                          Playwright configs, .env.template
    viewer/               step 4
  packages/
    ui/                   @open-reaction-database/ui, "private": true
      package.json  tsconfig.json  vitest.config.ts  README.md
      src/
        theme/            Mantine theme, CSS variables, color and type modules, icons
        display/          KeyValueDisplay, RequiredOptionalFields, DataField, Counter
        shell/            PageContainer, Breadcrumbs, Footer
        reaction/         model and converters, provider and hooks, previews, cards,
                          sections, header, drawer and forms
        testing/          renderWithReaction and fixtures
```

`frontend/` follows the usual pattern for a repository that holds Python and JavaScript:
the JavaScript workspace gets its own directory, and inside it `apps/` holds what
deploys while `packages/` holds what is shared. The Python layout is step 3's decision.

### Package rules

- **Dependencies are declared.** React, React DOM, Mantine, `@bufbuild/protobuf`, and the
  ORD SDK are `peerDependencies`; Indigo and the other leaf libraries are
  `dependencies`. wouter is a peer dependency that only `shell/` imports.
  `import/no-extraneous-dependencies` checks every import against the package's own
  `package.json`, because hoisting would otherwise let an undeclared import resolve.
- **`exports` is the public surface:** `./theme`, `./display`, `./shell`, `./reaction`,
  and `./testing`. Apps import only through it; a lint rule rejects deep imports such as
  `@open-reaction-database/ui/src/...`.
- **Internal imports use `package.json` `imports`** (`#theme/...`, `#reaction/...`),
  which travel with the package where tsconfig `paths` would not. Step W2 confirms that
  Vite, Vitest, and `tsc -b` resolve them; if any does not, the package uses relative
  imports instead.
- **Apps consume TypeScript source.** `exports` point at `src/`, and each app's Vite
  compiles the package, so there is no library build to run or keep in sync.
- **The editor's imports are unchanged.** `apps/editor` keeps its bare `paths` mapping
  (`store/...`, `common/...`). Converting it touches every file and is a separate
  cleanup.

## The provider

Every rendered reaction — a page, a template page, a list card — sits under one
`ReactionProvider`. Code in `packages/ui` reads and changes a reaction only through the
provider's hooks.

```ts
/** One reaction's data. The editor adapts its Redux store; the viewer wraps a plain object. */
interface ReactionSource {
  /** Returns the same object until the reaction changes. */
  getSnapshot(): ReactionSnapshot | undefined;
  /** SVGs keyed by component ID; same stability rule. */
  getPreviews(): PreviewsById;
  subscribe(listener: () => void): () => void;
}

/** The store's own object, so the Redux source needs no mapping to stay stable. */
type ReactionSnapshot = BaseReaction &
  Partial<Pick<DatasetReaction, 'pb_reaction_id' | 'is_valid' | 'validation'>>;

/** Present only when the reaction can be edited. */
interface ReactionActions {
  update(path: ReactionPathComponents, value: unknown): void;
  remove(path: ReactionPathComponents): void;
  lookupCompound(query: string): Promise<LookupResult>;
  currentPerson?(): Person | undefined;
}

interface ReactionLinks {
  /** Where a reaction ID links to, or undefined for no link. */
  reaction(pbReactionId: string): string | undefined;
}

<ReactionProvider
  source={source}
  actions={actions}          // omitted ⇒ read-only
  isTemplate={false}
  links={links}
  slots={{ ViewDeleteButtons, ValueLabel, ViewOnlyLabel, HeaderActions }}
>
```

The `ReactionActions` methods above come from the dispatch inventory below; step E
settles the final list.

### Hooks

| Hook | Replaces |
| --- | --- |
| `useReactionPart(path)` | `useSelector(selectReactionPartByPath(id, path))`, 15 files |
| `useReactionSnapshot()` | `useSelector(selectReactionById(id))`, in the shared callers among its 15 |
| `useOrderedInputs()` | `selectOrderedInputsWrapper`, 2 files |
| `usePreviews(ids)` | `selectPreviewsByIdsWrapper`, 4 files |
| `useReactionActions()` | direct dispatches of `addUpdateReactionField` (10 files), `deleteReactionField`, `addIdentifierByName`, the lookup thunks |
| `useIsViewOnly()` | `isViewOnly` from `reactionContext`, 24 files; true when no `actions` were supplied |
| `useDrawer()` | the `features.reactionForm` slice and its five actions |
| `useReactionLinks()`, `useReactionSlots()` | `reactionContext`'s injected components, and hard-coded editor routes |

The data hooks use `useSyncExternalStoreWithSelector`, so a component re-renders when
what it selected changes, as it does with `useSelector` today. The reducer rebuilds a
reaction's `data` with a deep merge on every edit, so an edit re-renders every reader of
that reaction, today and after; readers of other reactions do not re-render.

### What moves out of Redux

- **The drawer's stack** (`features.reactionForm`) becomes `useReducer` state inside the
  provider. Only `ReactionDetailsSidebar`, the View buttons, `ReactionValidationList`,
  and the templates' `VariablesSidebar` use it, all inside the provider. The provider is
  keyed by reaction, so the stack resets on navigation, which the reducer did by hand on
  `searchReactionActions.success`.
- **The compound lookup's flags** (`features.reactionLookup`) become local state in
  `ComponentsLookup` and `CustomIdentifiers`, with the request going through
  `actions.lookupCompound`.
- **The preview worker** becomes a plain module, `reaction/previews`:
  `renderPreviews(molblocksById): Promise<Record<string, string>>`, which owns
  `initIndigo()` (moved out of `src/core/AppRoot.tsx`). The editor's
  `previewsWorkerMiddleware` calls it; the plain source calls it and notifies its
  subscribers when the SVGs arrive.

### What stays in the editor

Templates' variables and `VariablesSidebar`, enumeration, Save as Template, rename,
remove, downloads, the dataset list with its pagination and filters, and the users,
groups, and datasets slices. They plug in through `slots` and `actions`. The header's
action buttons become the `HeaderActions` slot, which also keeps `EnumerationWizard`,
`SaveAsTemplate`, and their Redux imports out of the package. `CrudeComponentView`'s
`searchReaction` thunk, which looks a reaction up and navigates to an editor route,
becomes a link from `useReactionLinks()`.

### Sources

- `reduxReactionSource(store, reactionId)`, in the editor, returns
  `reactionsById[reactionId]` and the previews slice as they are, so `getSnapshot` is
  stable without memoization. It handles numeric dataset IDs and the templates' string
  IDs alike.
- `createStaticReactionSource(snapshot)`, in the package, holds a fixed snapshot and
  fills previews through `reaction/previews`. The viewer and the tests use it.

## Migration

Each step is its own PR, keeps the editor's behavior, and is green on its own.
[ord-app#837](https://github.com/open-reaction-database/ord-app/pull/837)
(protobuf-es) lands first: it edits 23 of the same files, though none of the store
touchpoints. Open UI PRs should land or rebase before W; Git follows the renames.

| Step | Change | Size |
| --- | --- | --- |
| W1 | Create the workspace: `git mv ui frontend/apps/editor`, root tool configs, and the files listed below. No source changes. | moves everything; ~15 edited |
| W2 | Create `packages/ui` with the theme and the display primitives that have no store dependencies (`KeyValueDisplay`, `RequiredOptionalFields`, `DataField`, `Counter`), with their tests, and lint its dependencies. | ~45 |
| A | Add `ReactionProvider`, the hooks, `reduxReactionSource`, and `createStaticReactionSource` in `apps/editor/src/features/reactions/provider/`, linted to stay free of the store. Wrap `ReactionPage` and `TemplatePage`; the provider supplies `reactionContext` too. Add the Playwright flows and screenshots. No consumers yet. | ~12 |
| B | Display reads: sections, previews, header, cards, validation results use the hooks. Wrap the list cards; add the provider's `links`. | ~21 |
| C | The drawer's stack moves into the provider; delete `features.reactionForm`. | ~8 |
| D | Form reads: `buildUseInitialValues`, `buildUseSelectItems`, `reactionEntityToValidation`, and the custom nodes use the hooks. | ~16 |
| E | Edits go through `useReactionActions()`; the lookup flags move to local state; delete `features.reactionLookup`. The editor supplies `actions` only for an editable dataset. Read-only drawers lose the Delete icon `ReactionEntityTitle` shows today whenever `hasDelete` is set. | ~14 |
| F | The preview worker becomes `reaction/previews`; the middleware calls it. | ~4 |
| G | Move the provider, the decoupled code, the icons, `ReactionComponentPreview`, `renderValuePrecisionUnit`, `AppReaction` and its converters (`ordBinpbToReaction`, `getReactionPreviews`, `parseValidation`, `getDeepReactionPart`, the copy and paste models) into `packages/ui/src/reaction` and the shell into `src/shell`. `PageContainer` takes header slots instead of importing `UserMenu`. | ~60 moved |

B through F depend on A, which adds every hook, and not on each other. G comes last.
The viewer (step 4) starts after G.

### Files W1 updates

| File | Change |
| --- | --- |
| `.github/workflows/ui_checks.yml` | `ui/**` path filters and `working-directory: ./ui` become `frontend/`; coverage upload path |
| `.github/workflows/tests.yml` | `test_e2e` working directories and the Playwright report paths |
| `.github/workflows/checks.yml` | jscpd's binary and `cache-dependency-path` |
| `.jscpd.json`, `Makefile` | scanned paths and the `duplication` target |
| `.pre-commit-config.yaml` | prettier, eslint, and stylelint hook paths |
| `Dockerfile.single`, `.dockerignore` | copy `frontend/`, `npm ci` at the root, build `-w apps/editor` |
| `CLAUDE.md`, `README.md`, `.claude/rules/ui-testing.md`, `.claude/skills/ord-app-ui-testing/SKILL.md` | paths and commands |
| `ui/vite.config.ts`, `ui/.env.template`, `ui/UI_Generated_Documentation.md` | paths that name `ui/` |

CI job names stay `lint_and_build_ui`, `test_ui`, and `test_e2e`: branch protection
matches required checks by name, so renaming them would drop the gates silently.
Dependabot covers only GitHub Actions today, so it needs no change.

## Testing

- **One Vitest config per workspace.** Vitest applies coverage options at the root of
  a projects run, so each app and package keeps its own config and floors, and the
  root `test:coverage` script runs each. The editor keeps its floors (lines 60,
  statements 60, branches 57, functions 60). `packages/ui` starts at its measured
  coverage after W2 and is raised as code moves in.
- **`renderWithReaction(reaction, { actions, previews })`**, exported from
  `./testing`, renders under a plain source. Tests of shared components use it instead
  of building a Redux store; the editor keeps `renderWithProviders` for its pages.
- **A contract suite** runs against both sources (in A with small fixtures; B and D add
  the full-reaction fixture from ord-app#837): the same snapshot gives the same hook output; the Redux source notifies
  subscribers when a field changes and returns the same snapshot when nothing did; and
  with no `actions` no edit control renders.
- **Refactor PRs keep their assertions.** Only the render harness changes. A changed
  assertion is called out in its PR; E's Delete icon is the only one expected.
- **Playwright**, added in A on the no-auth stack `test_e2e` already boots: open a
  reaction, switch tabs and list, and open and close the drawer. E adds the check that a
  read-only dataset shows no edit or Delete controls, when it changes that behavior. A few `toHaveScreenshot` captures (reaction
  page, open drawer, dataset card) catch look changes through G, when moving SCSS modules
  can reorder CSS. Baselines are generated in CI's Linux container and compared only
  there.
- **Static checks.** `tsc -b` at the root through project references; eslint with
  `import/no-extraneous-dependencies` and the deep-import ban; jscpd across `frontend/`.

## Risks

- **Conflicts.** W1 moves every frontend file. Land or rebase the open UI PRs first, and
  schedule W1 when few are open.
- **Snapshot stability.** A `getSnapshot` that builds a new object on every call makes
  `useSyncExternalStore` loop. The contract suite checks that an unchanged store returns
  the same snapshot.
- **The lockfile.** Moving to a workspace regenerates `package-lock.json`. W's diff
  should change locations, not versions; any version change is a bug in the move.
- **Bundle size.** The drawer imports Ketcher statically through `CustomIdentifiers`.
  It is editor-only in practice, so G makes it a lazy import before the viewer depends
  on the drawer.
- **Subpath imports.** If `#...` imports fail anywhere in the toolchain, the package uses
  relative imports; nothing else in the design changes.

## Not in this step

The viewer app (step 4), the search backend (step 3), deployment (step 5), publishing
the package, replacing Redux in the editor, and converting the editor's bare imports.
