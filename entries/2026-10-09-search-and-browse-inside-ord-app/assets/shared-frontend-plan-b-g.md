# Shared frontend package: implementation plan for B through G

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** ready to execute; B starts from ord-app `main` at
  [`65ac1eb`](https://github.com/open-reaction-database/ord-app/commit/65ac1eb)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every reaction read, the drawer's stack, and every reaction edit onto the
`ReactionProvider` that PR A added (B–E), make the preview renderer a plain module (F),
and move the decoupled code into `@open-reaction-database/ui` (G), so a second app can
render a reaction without the editor's Redux store.

**Architecture:** Each step is its own PR from an up-to-date `main`, keeps the editor's
behavior, and is green on its own. B moves display reads to the hooks and puts a
provider around every rendered reaction. C replaces `features.reactionForm` with a
reducer inside the provider. D moves the drawer forms' reads to the hooks. E routes edits
through `useReactionActions()` and removes the drawer's Delete icon where the reaction
is read-only. F turns the preview worker into `reaction/previews` in the package. G moves
the model, the provider, the view, and the shell into the package in three PRs.

**Tech Stack:** npm workspaces, React 19, Mantine 7, Redux Toolkit, wouter 3, Vite 6,
Vitest 4 (happy-dom), Playwright, TypeScript 5.6 project references, ESLint 9 flat
config with `eslint-plugin-import-x`, `use-sync-external-store`, `indigo-ketcher`.

**Spec:** [`shared-frontend-design.md`](shared-frontend-design.md), beside this file.
Read it first, then [`shared-frontend-plan.md`](shared-frontend-plan.md), which built
the ground this plan stands on (W1, W2, A). Where this plan refines the design, the
[Refinements](#refinements-to-the-design) section says how, and the design has been
updated to match.

## Global Constraints

- Repository: `open-reaction-database/ord-app`, local checkout `~/ord/ord-app`. Every PR
  starts from an up-to-date `main` on its own branch, after the previous PR has merged.
  Never commit to `main`; never force-push; work in the checkout, not a worktree.
- Order: B, C, D, E, F, then G1, G2, G3. F depends only on A and may run before or
  between the others; everything else runs in order.
- Each PR keeps the editor's behavior except where a task says otherwise. Existing test
  assertions stay as they are; only render harnesses, props, and import paths change.
  A changed assertion is listed in its PR body under `## Notes`, with the reason.
- Baseline on `main` at `65ac1eb`: `apps/editor` Vitest 240 files, 825 tests;
  `packages/ui` 5 files, 8 tests. Each task's Expected lines are relative to the counts
  the previous task left; each PR body states its final counts.
- CI job names stay `lint_and_build_ui`, `test_ui`, `test_e2e`, `check_duplication`.
- Every new `.ts`, `.tsx`, `.scss`, `.mjs`, and `.cjs` file starts with the Apache-2.0
  header, copyright 2026, "Open Reaction Database Project Authors". Code blocks below
  omit it. A moved file keeps its header.
- The editor keeps its bare imports (`store/…`, `common/…`, `features/…`). Code inside
  `packages/ui` imports its own files through `#…` or from the same folder, never `../`.
- `features/reactions/provider/` stays free of runtime imports from `store/`, Redux,
  axios, Auth0, and wouter (the lint block in `frontend/eslint.config.mjs` enforces it).
  Type imports from `store/` are allowed there until G1 moves the types.
- `packages/ui` never imports Redux, react-redux, axios, Auth0, or editor code; only
  `src/shell/` may import wouter.
- Type-check with `npm run typecheck` (`tsc -b`) from `frontend/`, never bare
  `tsc --noEmit`.
- Unit tests for one file: `cd ~/ord/ord-app/frontend/apps/editor && npx vitest run <path>`
  (paths relative to `apps/editor`). Package tests:
  `cd ~/ord/ord-app/frontend/packages/ui && npx vitest run <path>`.
- Full check before each PR, from `~/ord/ord-app/frontend`:
  `npm run lint:check && npm run typecheck && npm run test:coverage && npm run build`,
  then `cd .. && frontend/node_modules/.bin/jscpd --config .jscpd.json`.
- `$SCRATCH` is a directory outside the repository for notes and PR bodies (the session
  scratchpad, or `mktemp -d`). Codemods use `perl -pi`, which behaves the same on macOS
  and Linux. The shell is zsh: quote globs.
- Comments say what the code does and why, never what changed. American spelling.
- Commit messages end with
  `Co-Authored-By: <the model you are running as> <noreply@anthropic.com>`. PR bodies
  follow `.github/PULL_REQUEST_TEMPLATE.md` (`## Summary`, `## Changes`, `## Testing`,
  `## Notes`), end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`,
  and are passed with `--body-file`.
- Stage paths by name (`git add <path> …`), never `git add -A`.
- Playwright screenshots are compared only in CI. A new baseline comes from CI: push,
  let `test_e2e` fail with "A snapshot doesn't exist", download the
  `playwright-report` artifact, inspect the PNG, commit it under the spec's
  `-snapshots/` directory, and push again.

## Review Focus

1. **Navigating from one reaction to another without leaving the page** (a crude
   component's reaction link, the browser's Back button between two cached reactions).
   Expected: the drawer starts closed and the sections show the new reaction. wouter
   does not remount the page, so this rests on the provider's `key`. Pinned in Task C2.
2. **A template, which is read-only, has a string ID, and has no validation.** Expected:
   sections and previews render, buttons read "Set variables", the validation badges
   render nothing, the drawer shows no Delete icon. Pinned in Tasks B3 (labels), B4
   (validation), D2 (value labels), and E4 (Delete).
3. **A dataset the signed-in user may only view.** Expected: no Edit, Add, Delete,
   Save, Paste, "Use my info", or lookup control anywhere, the drawer included. Pinned in
   Tasks E4 (component) and E5 (Playwright).
4. **Previews that cannot render**, because Indigo fails to load or a molblock is bad.
   Expected: the spinners stop and the "No preview" icon shows. Pinned in Task F2.
5. **A page of reaction cards**, each under its own provider. Expected: every card's
   previews arrive, from one preview worker. Pinned in Tasks B3 (cards) and F1 (one
   worker).

---

## PR B: display reads use the hooks

Branch `reaction-display-hooks`. The nine sections, the previews, the cards, the
validation results, and the reaction header read through the provider's hooks. Every
place that renders a reaction preview gets a provider of its own. The editor-owned parts
of the header become props, and the crude component's reaction link becomes a slot.

Paths in this PR are relative to `frontend/apps/editor/src/` unless they start with
`frontend/` or `e2e/`.

### Task B1: A screenshot of a dataset card, taken before B changes the card

The design's third screenshot. Its baseline has to come from the card as `main` renders
it, so this task goes first and the PR opens as a draft to get it from CI.

**Files:**

- Modify: `frontend/apps/editor/e2e/seed.ts` (return the group ID too)
- Create: `frontend/apps/editor/e2e/datasetPage.spec.ts`
- Create (from CI): `frontend/apps/editor/e2e/datasetPage.spec.ts-snapshots/dataset-card-chromium-linux.png`

**Interfaces:**

- Produces: `seedReaction(request): Promise<{ groupId: number; datasetId: number; reactionId: number }>`
  (E5 uses `groupId`).

- [ ] **Step 1: Branch**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c reaction-display-hooks
cd frontend && npm ci
```

- [ ] **Step 2: Return the group from the seed**

In `e2e/seed.ts`, change the return type and value of `seedReaction`:

```ts
): Promise<{ groupId: number; datasetId: number; reactionId: number }> {
  …
  return { groupId: group.id, datasetId: dataset.id, reactionId: reaction.id };
```

- [ ] **Step 3: The spec**

`e2e/datasetPage.spec.ts`:

```ts
import { expect, test } from '@playwright/test';
import { seedReaction } from './seed.ts';

const PREVIEW = 'img[src^="data:image/svg+xml"]';
const LOADER = '.mantine-Loader-root';

let datasetUrl: string;

test.beforeAll(async ({ request }) => {
  const { datasetId } = await seedReaction(request);
  datasetUrl = `/datasets/${datasetId}`;
});

test.describe('appearance', () => {
  // A missing baseline is written by the attempt that finds it missing; a retry would then
  // match it and pass, so this test does not retry.
  test.describe.configure({ retries: 0 });

  test('a reaction card looks the same', async ({ page }) => {
    // The baselines are rendered on CI's Linux runner; fonts and antialiasing differ
    // elsewhere, so a local comparison would fail on rendering alone.
    test.skip(
      !process.env.CI,
      'Screenshots are compared only in CI, where the baselines are made.',
    );
    await page.goto(datasetUrl, { waitUntil: 'domcontentloaded' });
    const link = page.getByRole('link', { name: 'e2e-reaction-page' });
    await expect(link).toBeVisible({ timeout: 30_000 });
    const card = page.locator('.mantine-Paper-root').filter({ has: link });
    // Edit rights arrive with the dataset; Remove shows once they have.
    await expect(card.getByRole('button', { name: 'Remove', exact: true })).toBeVisible();
    // Two input previews and one product preview, from the Indigo worker.
    await expect(card.locator(LOADER)).toHaveCount(0);
    await expect(card.locator(PREVIEW)).toHaveCount(3);
    await expect(card).toHaveScreenshot('dataset-card.png');
  });
});
```

The card's link text is the fixture's `reaction_id` (`e2e/fixtures/reaction.pbtxt`). If
the Remove button on the card is not labeled "Remove", read the card with
`npx playwright test --debug` and match what `RemoveReaction` renders.

- [ ] **Step 4: Run it locally**

```bash
cd ~/ord/ord-app && scripts/dev-e2e.sh   # in its own terminal; see the ord-app-ui-testing skill
cd ~/ord/ord-app/frontend/apps/editor && npx playwright test e2e/datasetPage.spec.ts e2e/reactionPage.spec.ts
```

Expected: the dataset test is skipped (no `CI`), the reaction page tests pass.

- [ ] **Step 5: Commit, push, and open a draft PR for the baseline**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/e2e/seed.ts frontend/apps/editor/e2e/datasetPage.spec.ts
git commit -F "$SCRATCH/b1-msg.txt"   # "Add a screenshot test of a dataset's reaction card"
git push -u origin reaction-display-hooks
gh pr create --draft --title "Read the reaction display through ReactionProvider" \
  --body-file "$SCRATCH/b-body.md"
```

`$SCRATCH/b-body.md` can be a stub for now (Summary only, with the footer); Task B9
writes the full body. `test_e2e` fails with "A snapshot doesn't exist". Download the
`playwright-report` artifact, open `dataset-card-chromium-linux.png` (under
`test-results/…/` as the actual image), confirm it shows one complete card with three
molecule images and no spinner, and commit it:

```bash
mkdir -p frontend/apps/editor/e2e/datasetPage.spec.ts-snapshots
cp <artifact>/…/dataset-card-actual.png \
  frontend/apps/editor/e2e/datasetPage.spec.ts-snapshots/dataset-card-chromium-linux.png
git add frontend/apps/editor/e2e/datasetPage.spec.ts-snapshots
git commit -F "$SCRATCH/b1b-msg.txt"   # "Add the dataset card's screenshot baseline"
git push
```

Expected: the next `test_e2e` run passes. Do not start Task B5 (the header) or B3 (the
cards) until this baseline is committed.

### Task B2: The test harness mounts `ReactionProvider`, and `useIsTemplate`

`renderInReactionView` hand-builds the legacy `reactionContext`, so a component that calls
a provider hook throws in its tests. The harness mounts the real provider over a Redux
source instead; the provider supplies the same legacy values, so every existing test
keeps its assertions.

**Files:**

- Modify: `test/renderInReactionView.tsx`
- Create: `test/renderInReactionView.test.tsx`
- Modify: `features/reactions/provider/reactionProvider.hooks.ts` (add `useIsTemplate`)
- Modify: `features/reactions/provider/reactionProvider.hooks.test.tsx`

**Interfaces:**

- Consumes: `ReactionProvider`, `reduxReactionSource`, `reduxReactionActions` (A).
- Produces:
  - `renderInReactionView(ui, options)` with options
    `{ reactionId?: number | string; pathComponents?; reaction?: AppReaction; record?: Partial<Omit<DatasetReaction, 'id' | 'data'>>; isViewOnly?: boolean; actions?: ReactionActions; slots?: Partial<ReactionSlots> }`.
    A string `reactionId` renders a template (read-only). Without `isViewOnly` or
    `actions`, the reaction is editable through `reduxReactionActions`. Returns
    `{ store, ...RenderResult }` as before.
  - `useIsTemplate(): boolean`.

- [ ] **Step 1: Write the failing tests**

`test/renderInReactionView.test.tsx`:

```tsx
import { useContext } from 'react';
import { reactionContext } from 'features/reactions/reactions.context.ts';
import {
  useIsTemplate,
  useIsViewOnly,
  useReactionSnapshot,
} from 'features/reactions/provider/reactionProvider.hooks.ts';
import { renderInReactionView } from './renderInReactionView.tsx';

function Probe() {
  const snapshot = useReactionSnapshot();
  const legacy = useContext(reactionContext);
  return (
    <dl>
      <dt>view only</dt>
      <dd>{String(useIsViewOnly())}</dd>
      <dt>template</dt>
      <dd>{String(useIsTemplate())}</dd>
      <dt>legacy id</dt>
      <dd>{String(legacy.reactionId)}</dd>
      <dt>pb id</dt>
      <dd>{snapshot?.pb_reaction_id ?? 'none'}</dd>
    </dl>
  );
}

const shown = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('dd'), dd => dd.textContent);

describe('renderInReactionView', () => {
  it('renders an editable dataset reaction under ReactionProvider by default', () => {
    const { container } = renderInReactionView(<Probe />);
    expect(shown(container)).toEqual(['false', 'false', '1', 'none']);
  });

  it('renders a read-only reaction, with the stored record fields it is given', () => {
    const { container } = renderInReactionView(<Probe />, {
      isViewOnly: true,
      record: { pb_reaction_id: 'ord-1' },
    });
    expect(shown(container)).toEqual(['true', 'false', '1', 'ord-1']);
  });

  it('renders a template for a string ID', () => {
    const { container } = renderInReactionView(<Probe />, { reactionId: 'template_1' });
    expect(shown(container)).toEqual(['true', 'true', 'template_1', 'none']);
  });
});
```

In `reactionProvider.hooks.test.tsx`, import `useIsTemplate` and add to the
`'reaction hooks over a static source'` block:

```tsx
  it('report whether the reaction is a template', () => {
    expect(renderHook(useIsTemplate, { wrapper }).result.current).toBe(false);
    function TemplateWrapper({ children }: Readonly<{ children: ReactNode }>) {
      return (
        <ReactionProvider
          reactionId="template_1"
          isTemplate
          source={source}
          slots={slots}
        >
          {children}
        </ReactionProvider>
      );
    }
    expect(renderHook(useIsTemplate, { wrapper: TemplateWrapper }).result.current).toBe(
      true,
    );
  });
```

- [ ] **Step 2: Run them to see them fail**

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/test/renderInReactionView.test.tsx src/features/reactions/provider/reactionProvider.hooks.test.tsx
```

Expected: FAIL — `useIsTemplate` is not exported; the harness tests throw "Reaction hooks
must be used inside a ReactionProvider."

- [ ] **Step 3: Add `useIsTemplate`**

In `reactionProvider.hooks.ts`, after `useIsViewOnly`:

```ts
/** Whether the reaction is a template, which is always read-only. */
export function useIsTemplate(): boolean {
  return useProviderValue().isTemplate;
}
```

- [ ] **Step 4: Mount the provider in the harness**

Replace the body of `test/renderInReactionView.tsx` below `emptyReactionData()` (keep the
license header, the eslint comments, and `emptyReactionData`):

```tsx
import { ReactionProvider } from 'features/reactions/provider/ReactionProvider.tsx';
import type {
  ReactionActions,
  ReactionSlots,
} from 'features/reactions/provider/reactionProvider.types.ts';
import {
  reduxReactionActions,
  reduxReactionSource,
} from 'store/entities/reactions/reduxReactionSource.ts';
import type { DatasetReaction } from 'store/entities/reactions/reactions.types.ts';

const Dummy = () => null;

const DUMMY_SLOTS: ReactionSlots = {
  ViewDeleteButtons: Dummy,
  ValueLabel: Dummy,
  ViewOnlyLabel: Dummy,
};

/** A dataset reaction, editable unless `isViewOnly`, or a template (a string ID, read-only). */
type ReactionViewTarget =
  | { reactionId?: number; isViewOnly?: boolean; actions?: ReactionActions }
  | { reactionId: string; isViewOnly?: never; actions?: never };

type ReactionViewOptions = Omit<RenderOptions, 'wrapper'> &
  ReactionViewTarget & {
    pathComponents?: ReactionPathComponents;
    reaction?: AppReaction;
    /** Stored fields beside `data`, such as `pb_reaction_id`, `is_valid`, or `validation`. */
    record?: Partial<Omit<DatasetReaction, 'id' | 'data'>>;
    slots?: Partial<ReactionSlots>;
  };

/**
 * Renders a component of the reaction view under ReactionProvider, over a store that holds the
 * reaction, with `reactionEntityContext` set to `pathComponents`.
 */
export function renderInReactionView(
  ui: ReactElement,
  options: ReactionViewOptions = {},
) {
  const {
    reactionId = 1,
    pathComponents = [],
    reaction,
    record,
    isViewOnly = false,
    actions,
    slots,
    ...renderOptions
  } = options;
  const store = configureStore({
    reducer: rootReducer,
    preloadedState: {
      entities: {
        reactions: {
          reactionsById: {
            [reactionId]: {
              id: reactionId,
              data: reaction ?? emptyReactionData(),
              previews: {},
              summary: { provenance: {}, summary: {}, conditions: '' },
              ...record,
            },
          },
        },
      },
    } as unknown as AppState,
  });
  // Built once, outside Wrapper, so a rerender keeps the same source and actions.
  const source = reduxReactionSource(store, reactionId);
  const target =
    typeof reactionId === 'string'
      ? { reactionId, isTemplate: true as const }
      : {
          reactionId,
          actions: isViewOnly
            ? undefined
            : (actions ?? reduxReactionActions(store.dispatch, reactionId)),
        };
  const allSlots = { ...DUMMY_SLOTS, ...slots };
  function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return (
      <Provider store={store}>
        <MantineProvider>
          <ReactionProvider
            {...target}
            source={source}
            slots={allSlots}
          >
            <reactionEntityContext.Provider value={{ reactionId, pathComponents }}>
              {children}
            </reactionEntityContext.Provider>
          </ReactionProvider>
        </MantineProvider>
      </Provider>
    );
  }
  return { store, ...render(ui, { wrapper: Wrapper, ...renderOptions }) };
}
```

Remove the imports that are now unused (`reactionContext`, `ReactionsContext`) and the
old comment about the template variant.

- [ ] **Step 5: Run the harness tests, then everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/test/renderInReactionView.test.tsx src/features/reactions/provider/reactionProvider.hooks.test.tsx
npx vitest run 2>&1 | tail -5
```

Expected: PASS; full run 241 files, 829 tests (825 + 3 harness + 1 hook), all passing.
A failure in a test that used the old harness means the provider's legacy context
differs from what the harness built by hand: compare the two, fix the harness, and do
not touch the test.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/test/renderInReactionView.tsx \
  frontend/apps/editor/src/test/renderInReactionView.test.tsx \
  frontend/apps/editor/src/features/reactions/provider/reactionProvider.hooks.ts \
  frontend/apps/editor/src/features/reactions/provider/reactionProvider.hooks.test.tsx
git commit -F "$SCRATCH/b2-msg.txt"   # "Render reaction view tests under ReactionProvider"
```

### Task B3: The nine sections and their rows read the hooks

**Files:**

- Modify: `features/reactions/ReactionView/{Conditions,Identifiers,Notes,Observation,Outcomes,Provenance,Setup,Workups}/*.tsx`, `ReactionView/Inputs/Inputs.tsx`
- Modify: `ReactionView/OpenSingleEntityButton/OpenSingleEntityButton.tsx`
- Modify: `ReactionView/ComponentsList/{ComponentDisplayRow,ComponentDisplayRowCustomActions}.tsx`
- Modify: `ReactionView/Inputs/InputsComponentsList/InputComponentsListItem/InputComponentsListItem.tsx`
- Modify: `ReactionView/Outcomes/OutcomeListItem/{OutcomeListItem,OutcomeListItemHeader}.tsx`
- Delete: `ReactionView/reactionView.types.ts`
- Modify: `features/reactions/ReactionEntities/ReactionTabs/{ReactionTabs,ReactionContent}.tsx`
- Modify: `pages/ReactionPage/ReactionPage.tsx`, `pages/TemplatePage/TemplatePage.tsx`
- Modify tests: `Conditions.test.tsx`, `Identifiers.test.tsx`, `Observation.test.tsx`,
  `Setup.test.tsx`, `OutcomeListItem.test.tsx`, `OutcomeListItemHeader.test.tsx`,
  `ReactionContent.test.tsx` (drop removed props), `OpenSingleEntityButton.test.tsx`,
  `ComponentDisplayRowCustomActions.test.tsx` (harness)
- Modify: `pages/TemplatePage/TemplatePage.test.tsx` only if it passes `reactionId` to the
  mocked `ReactionTabs` in an assertion (it mocks the component, so most likely no change)

**Interfaces:**

- Consumes: `useReactionPart`, `useOrderedInputs`, `usePreviews`, `useIsViewOnly`,
  `useIsTemplate`, `useReactionSlots` (A, B2).
- Produces: the sections, `ReactionTabs`, and `ReactionContent` take no `reactionId`
  (`<ReactionTabs />`, `<ReactionContent viewMode={…} />`); `OutcomeListItem` and
  `OutcomeListItemHeader` take no `reactionId`.

The sections that create entities (Identifiers, Observation, Workups, and Inputs and
Outcomes through `buildUseCreate`) keep dispatching until C and E replace those
dispatches. Where a section dispatched with its `reactionId` prop, it reads the ID from
`reactionContext` for the dispatch alone.

- [ ] **Step 1: Make the two harness-less tests fail first**

`OpenSingleEntityButton.test.tsx` renders the button with no provider. Replace its body
with tests of the three labels (a stronger version of the smoke test; the old assertion
that it mounts still holds in each):

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { OpenSingleEntityButton } from './OpenSingleEntityButton.tsx';

describe('OpenSingleEntityButton', () => {
  it.each([
    [{}, 'Edit'],
    [{ isViewOnly: true }, 'View'],
    [{ reactionId: 'template_1' }, 'Set variables'],
  ] as const)('with %o reads %s', (options, label) => {
    const { getByRole } = renderInReactionView(
      <OpenSingleEntityButton pathComponents={['notes']} />,
      options,
    );
    expect(getByRole('button', { name: label })).toBeInTheDocument();
  });
});
```

In `ComponentDisplayRowCustomActions.test.tsx`, replace `renderWithProviders(` with
`renderInReactionView(` (import from `test/renderInReactionView.tsx`); the assertions stay.

Run them; the label tests pass against today's code (it reads `reactionContext`, which
the harness now supplies), which is fine: they pin the behavior the change must keep.

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/features/reactions/ReactionView/OpenSingleEntityButton src/features/reactions/ReactionView/ComponentsList
```

Expected: PASS.

- [ ] **Step 2: Sections read the hooks**

Each change replaces a store read with a hook, as below. Keep everything else in each
file as it is.

`Conditions.tsx` (and the same shape in `Notes.tsx`, `Provenance.tsx`, `Setup.tsx`, with
their own `ENTITY_FIELD` and type):

```tsx
export function Conditions() {
  const conditions = useReactionPart<ReactionConditions>([ENTITY_FIELD]);
```

`Notes.tsx` and `Provenance.tsx` drop `const { reactionId } = useContext(reactionContext);`.
A section whose value can now be `null` where the old selector typing said it could not
(`ReactionConditions`, `ReactionSetup`, `ReactionProvenance`) keeps today's runtime
behavior: the old selector also returned `null` for a missing reaction. Add `!` only if
`tsc -b` requires it and the file already dereferences without a guard; prefer the
existing optional chaining where there is some.

`Identifiers.tsx`:

```tsx
export function Identifiers() {
  const dispatch = useAppDispatch();
  // The ID only addresses the dispatch below; C and E replace that dispatch.
  const { reactionId } = useContext(reactionContext);
  const identifiers =
    useReactionPart<Array<ReactionIdentifier>>([ENTITY_FIELD]) ?? [];
  const isViewOnly = useIsViewOnly();
  const { ViewDeleteButtons } = useReactionSlots();
```

and render `<ViewDeleteButtons … />` where it rendered `<ViewDeleteButtonsComponent … />`.
`Observation.tsx` follows the same pattern with `['observations']` and
`Array<ReactionObservation>`; `Workups.tsx` with `['workups']`, `Array<ReactionWorkup>`,
`useIsViewOnly()`, and `useReactionSlots().ViewDeleteButtons`.

`Inputs.tsx`:

```tsx
export function Inputs() {
  const isViewOnly = useIsViewOnly();
  const inputs = useOrderedInputs();
```

`Outcomes.tsx`:

```tsx
export function Outcomes() {
  const outcomes = useReactionPart<Array<ReactionOutcome>>([ENTITY_FIELD]) ?? [];
  const onCreateNew = useCreate();
  const isViewOnly = useIsViewOnly();
```

Check how `Outcomes` used `outcomes` when it was `null` (the old test rendered it with no
`reactionId`, so `null` reached it): if it guarded `null` explicitly, keep the guard and
drop `?? []`; the visible result for an empty reaction must stay "no Outcomes".

`OpenSingleEntityButton.tsx`:

```tsx
  const dispatch = useAppDispatch();
  const isViewOnly = useIsViewOnly();
  const isTemplate = useIsTemplate();
```

`ComponentDisplayRow.tsx`, `InputComponentsListItem.tsx`, `OutcomeListItemHeader.tsx`:
`const { ViewDeleteButtons } = useReactionSlots();` in place of
`const { ViewDeleteButtonsComponent } = useContext(reactionContext);`, and rename the
JSX element.

`ComponentDisplayRowCustomActions.tsx`:

```tsx
  const previewState = usePreviews([component.id])[component.id];
```

and pass `previewState={previewState}` where it passed `previewState[component.id]`.

`OutcomeListItemHeader.tsx`: delete the unused `reactionId` prop from its props
interface. `OutcomeListItem.tsx`: delete its `reactionId` prop and stop passing it.
`Outcomes.tsx`: stop passing `reactionId` to `OutcomeListItem`.

Delete `ReactionView/reactionView.types.ts`. `ReactionTabs.tsx`: type `Component` as
`FC`, delete the `reactionId` prop and `TemplateTabsProps`, render `<Component />`.
`ReactionContent.tsx`: props `{ viewMode: 'tabs' | 'list' }`, render `<ReactionTabs />`
and each section with no props. `ReactionPage.tsx`: `<ReactionContent viewMode={viewMode} />`.
`TemplatePage.tsx`: `<ReactionTabs />`.

Drop the now-unused imports (`useSelector`, `selectReactionPartByPath`,
`selectReactionById`, `selectOrderedInputsWrapper`, `selectPreviewsByIdsWrapper`,
`ReactionId`); `npm run lint` reports any left.

- [ ] **Step 3: Update the tests that passed removed props**

Delete `reactionId={1}` from `<Conditions />`, `<Identifiers />`, `<Observation />`,
`<Setup />`, `<OutcomeListItem … />`, `<OutcomeListItemHeader … />`, and
`<ReactionContent … />` in their tests. No assertion changes.

- [ ] **Step 4: Run the tests and the type check**

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/features/reactions src/pages 2>&1 | tail -5
cd .. && cd .. && npm run typecheck && npm run lint
```

Expected: PASS; `tsc -b` and eslint clean. `grep -rn "selectReactionPartByPath\|selectReactionById\|selectOrderedInputsWrapper\|selectPreviewsByIdsWrapper" apps/editor/src/features/reactions/ReactionView`
prints nothing.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/ReactionView \
  frontend/apps/editor/src/features/reactions/ReactionEntities/ReactionTabs \
  frontend/apps/editor/src/pages/ReactionPage/ReactionPage.tsx \
  frontend/apps/editor/src/pages/TemplatePage/TemplatePage.tsx
git commit -F "$SCRATCH/b3-msg.txt"   # "Read the reaction sections through the provider's hooks"
```

`git status` must show `reactionView.types.ts` as deleted and staged.

### Task B4: Previews, cards, and validation results read the hooks; every preview has a provider

**Files:**

- Modify: `common/components/ReactionPreview/{ReactionPreview,ReactionInputPreview,ReactionOutcomePreview}.tsx`
- Modify: `common/components/ReactionCard/ReactionCard.tsx`
- Modify: `features/reactions/ReactionList/DatasetReactionCard/DatasetReactionCard.tsx`
- Modify: `features/reactions/ReactionHeader/ReactionValidationResult/ReactionValidationResult.tsx`
- Modify: `features/reactions/ReactionInteractions/ReactionNodeValidationResult/ReactionNodeValidationResult.tsx`
- Create: `features/reactions/useReduxReactionSource.ts`
- Create: `features/templates/TemplateReactionProvider/TemplateReactionProvider.tsx` and `templateReactionSlots.ts`
- Modify: `pages/TemplatePage/TemplatePage.tsx`, `pages/TemplatesList/TemplatesList.page.tsx`,
  `pages/ReactionPage/useDatasetReactionProviderProps.ts`
- Modify: `features/templates/TemplateHeader/TemplateHeader.tsx`, `features/enumeration/EnumerationSetup/EnumerationSetup.tsx`
- Modify: `features/reactions/ReactionHeader/ReactionHeader.tsx` (only the `ReactionPreview` and `ReactionValidationResult` props; B5 splits it)
- Modify tests: `ReactionPreview.test.tsx`, `ReactionInputPreview.test.tsx`,
  `ReactionOutcomePreview.test.tsx`, `ReactionCard.test.tsx`,
  `ReactionValidationResult.test.tsx`
- Create tests: `DatasetReactionCard.test.tsx`, `TemplateReactionProvider.test.tsx`,
  `ReactionNodeValidationResult.provider.test.tsx`

**Interfaces:**

- Consumes: `useReactionSnapshot`, `useReactionPart`, `useOrderedInputs`, `usePreviews`
  (A); `renderInReactionView` with `record` and string IDs (B2).
- Produces:
  - `ReactionPreview` takes no `reaction` prop (still forwards a ref to its wrapper).
  - `ReactionInputPreview({ inputId })`, `ReactionOutcomePreview({ outcomeIndex })`.
  - `ReactionCard({ title, actions, previewRef?, isInvalid? })` — no `id`; it must be
    rendered under a provider.
  - `ReactionValidationResult()` and `ReactionNodeValidationResult({ pathComponents })`
    read the snapshot and render nothing when `validation` is `null` or `undefined`.
  - `useReduxReactionSource(reactionId: ReactionId): ReactionSource` — memoized per
    store and ID.
  - `TemplateReactionProvider({ templateId: string; children })` — a template provider
    keyed by `templateId`, with `TEMPLATE_SLOTS`.
  - `TEMPLATE_SLOTS` exported from `features/templates/TemplateReactionProvider/templateReactionSlots.ts`.

- [ ] **Step 1: Write the failing tests**

`ReactionPreview.test.tsx`: render `<ReactionPreview />` with no prop (the harness seeds
`summary`); delete the hand-built `reaction` object. Assertions unchanged.

`ReactionInputPreview.test.tsx` and `ReactionOutcomePreview.test.tsx`: drop
`reactionId={1}`.

`ReactionCard.test.tsx`: replace the body with

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { ReactionCard } from './ReactionCard.tsx';

describe('ReactionCard', () => {
  it('renders the title, the actions, and the reaction preview', () => {
    const { getByText } = renderInReactionView(
      <ReactionCard
        title={<span>Card title</span>}
        actions={<button type="button">Act</button>}
      />,
    );
    expect(getByText('Card title')).toBeInTheDocument();
    expect(getByText('Act')).toBeInTheDocument();
    expect(getByText('There are no Inputs and Outcomes yet')).toBeInTheDocument();
  });
});
```

`ReactionValidationResult.test.tsx`: replace `renderWithProviders(<ReactionValidationResult reactionId={1} />, stateWith({...}))`
with `renderInReactionView(<ReactionValidationResult />, { record: {...} })`, passing the
same `is_valid` and `validation` values the test passed to `stateWith`; delete
`stateWith`. Assertions unchanged.

`ReactionNodeValidationResult.provider.test.tsx` (new; the existing test covers only the
display component):

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { ReactionNodeValidationResult } from './ReactionNodeValidationResult.tsx';

describe('ReactionNodeValidationResult under a provider', () => {
  it('shows the errors under its path', () => {
    const { getByText } = renderInReactionView(
      <ReactionNodeValidationResult pathComponents={['notes']} />,
      {
        record: {
          validation: {
            errors: [{ text: 'bad note', path: ['notes'] }],
            warnings: [],
          },
        },
      },
    );
    expect(getByText('1')).toBeInTheDocument();
  });

  it('renders nothing for a template, which has no validation', () => {
    const { container } = renderInReactionView(
      <ReactionNodeValidationResult pathComponents={['notes']} />,
      { reactionId: 'template_1' },
    );
    expect(container).toBeEmptyDOMElement();
  });
});
```

Read `ReactionNodeValidationResultDisplay` and `ReactionValidation` first and shape the
error object (its `path` form and what the badge shows) to match them; the point of the
first test is that a message under the path renders, so adjust the expected text to
what the display renders for one error.

`TemplateReactionProvider.test.tsx`:

```tsx
import { useIsTemplate, useReactionSnapshot } from 'features/reactions/provider/reactionProvider.hooks.ts';
import { renderWithProviders } from 'test/renderWithProviders.tsx';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import type { AppState } from 'store/configureAppStore.ts';
import { TemplateReactionProvider } from './TemplateReactionProvider.tsx';

function Probe() {
  const snapshot = useReactionSnapshot();
  return (
    <span>
      {String(useIsTemplate())} {snapshot ? 'loaded' : 'missing'}
    </span>
  );
}

describe('TemplateReactionProvider', () => {
  it('provides the template from the store, read-only', () => {
    const { getByText } = renderWithProviders(
      <TemplateReactionProvider templateId="template_3">
        <Probe />
      </TemplateReactionProvider>,
      {
        preloadedState: {
          entities: {
            reactions: {
              reactionsById: {
                template_3: { id: 'template_3', data: emptyReactionData(), previews: {} },
              },
            },
          },
        } as unknown as AppState,
      },
    );
    expect(getByText('true loaded')).toBeInTheDocument();
  });
});
```

`DatasetReactionCard.test.tsx` (`features/reactions/ReactionList/DatasetReactionCard/`):

```tsx
import { Route, Router } from 'wouter';
import { memoryLocation } from 'wouter/memory-location';
import type { AppState } from 'store/configureAppStore.ts';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import { renderWithProviders } from 'test/renderWithProviders.tsx';
import { DatasetReactionCard } from './DatasetReactionCard.tsx';

const state = (is_valid: boolean) =>
  ({
    entities: {
      reactions: {
        reactionsById: {
          4: {
            id: 4,
            pb_reaction_id: 'ord-four',
            is_valid,
            validation: null,
            data: emptyReactionData(),
            previews: {},
            summary: { provenance: {}, summary: {}, conditions: '' },
          },
        },
      },
    },
  }) as unknown as AppState;

function renderCard(is_valid: boolean) {
  const { hook } = memoryLocation({ path: '/datasets/2' });
  return renderWithProviders(
    <Router hook={hook}>
      <Route path="/datasets/:datasetId">
        <DatasetReactionCard
          reactionId={4}
          index={1}
        />
      </Route>
    </Router>,
    { preloadedState: state(is_valid) },
  );
}

describe('DatasetReactionCard', () => {
  it('links the reaction ID to its page and shows its preview', () => {
    const { getByRole, getByText } = renderCard(true);
    expect(getByRole('link', { name: 'ord-four' })).toHaveAttribute(
      'href',
      '/datasets/2/reactions/4',
    );
    expect(getByText('There are no Inputs and Outcomes yet')).toBeInTheDocument();
  });

  it('marks an invalid reaction', () => {
    expect(renderCard(false).getByText('Invalid reaction')).toBeInTheDocument();
  });
});
```

If wouter's `Link` with `~/` renders a different `href` under a memory location, assert
what it renders and say so in the commit; the test exists to prove the card renders
under its own provider.

Run them:

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/common/components/ReactionPreview src/common/components/ReactionCard \
  src/features/reactions/ReactionHeader src/features/reactions/ReactionInteractions/ReactionNodeValidationResult \
  src/features/reactions/ReactionList src/features/templates/TemplateReactionProvider
```

Expected: FAIL — `TemplateReactionProvider` does not exist; `ReactionCard` without `id`
renders nothing; the preview tests fail to type-check or render without `reaction`.

- [ ] **Step 2: The editor's source hook and the template provider**

`features/reactions/useReduxReactionSource.ts`:

```ts
import { useMemo } from 'react';
import { useStore } from 'react-redux';
import type { ReactionSource } from 'features/reactions/provider/reactionProvider.types.ts';
import type { AppState } from 'store/configureAppStore.ts';
import { reduxReactionSource } from 'store/entities/reactions/reduxReactionSource.ts';
import type { ReactionId } from 'store/entities/reactions/reactions.types.ts';

/** One source per reaction for the life of the component, read from the editor's store. */
export function useReduxReactionSource(reactionId: ReactionId): ReactionSource {
  const store = useStore<AppState>();
  return useMemo(() => reduxReactionSource(store, reactionId), [store, reactionId]);
}
```

Use it in `useDatasetReactionProviderProps.ts` (replacing its own `useMemo` over
`reduxReactionSource`) and in `TemplatePage.tsx` (below).

`features/templates/TemplateReactionProvider/templateReactionSlots.ts`: move
`TEMPLATE_SLOTS` (and its three imports) out of `TemplatePage.tsx`, exported.

`features/templates/TemplateReactionProvider/TemplateReactionProvider.tsx`:

```tsx
import type { ReactNode } from 'react';
import { ReactionProvider } from 'features/reactions/provider/ReactionProvider.tsx';
import { useReduxReactionSource } from 'features/reactions/useReduxReactionSource.ts';
import { TEMPLATE_SLOTS } from './templateReactionSlots.ts';

interface TemplateReactionProviderProps {
  templateId: string;
  children: ReactNode;
}

/** Provides one template, read-only, from the editor's store; a new ID remounts the view. */
export function TemplateReactionProvider({
  templateId,
  children,
}: Readonly<TemplateReactionProviderProps>) {
  const source = useReduxReactionSource(templateId);
  return (
    <ReactionProvider
      key={templateId}
      reactionId={templateId}
      isTemplate
      source={source}
      slots={TEMPLATE_SLOTS}
    >
      {children}
    </ReactionProvider>
  );
}
```

`TemplatePage.tsx`: replace its `<ReactionProvider …>` (and the `store`/`source` lines)
with `<TemplateReactionProvider templateId={templateId}>`.

- [ ] **Step 3: Previews and cards read the hooks**

`ReactionPreview.tsx`:

```tsx
export const ReactionPreview = forwardRef<HTMLDivElement>(
  function ReactionPreview(_props, ref) {
    const inputs = useOrderedInputs();
    const outcomes = useReactionPart<Array<ReactionOutcome>>(['outcomes']) ?? [];
    const conditions = useReactionSnapshot()?.summary.conditions ?? '';
```

and render `<ReactionInputPreview key={input.id} inputId={input.id} />` and
`<ReactionOutcomePreview key={outcome.id} outcomeIndex={index} />`. Delete
`ReactionPreviewProps`.

`ReactionInputPreview.tsx`:

```tsx
export function ReactionInputPreview({ inputId }: Readonly<ReactionInputPreviewProps>) {
  const input = useReactionPart<ReactionInput>(['inputs', inputId]);
  const componentsIds = useMemo(
    () => (input?.components ?? []).map(({ id }) => id),
    [input],
  );
  const componentsPreviews = usePreviews(componentsIds);
```

If the component dereferenced `input` without a guard after that, return `null` when
`input` is `null` (it never is for an ID taken from `useOrderedInputs`).
`ReactionOutcomePreview.tsx` takes the same shape with
`useReactionPart<ReactionOutcome>(['outcomes', outcomeIndex])` and `outcome.products`;
rename its props interface to `ReactionOutcomePreviewProps` while there.

`ReactionCard.tsx`: delete the `id` prop and the store read; read the summary from the
snapshot and render nothing until the reaction has loaded, as before:

```tsx
export function ReactionCard({
  title,
  actions,
  previewRef,
  isInvalid,
}: Readonly<ReactionCardProps>) {
  const summary = useReactionSnapshot()?.summary;
  if (!summary) {
    return null;
  }
```

with `summary.provenance` and `summary.summary` where it read `reaction.summary.…`, and
`<ReactionPreview ref={previewRef} />`.

- [ ] **Step 4: Validation results read the snapshot**

`ReactionValidationResult.tsx`: no props.

```tsx
export function ReactionValidationResult() {
  const [opened, { toggle, close }] = useDisclosure();
  const snapshot = useReactionSnapshot();
  const isValid = snapshot?.is_valid ?? false;
  const validation = snapshot?.validation ?? null;
  const hasErrorsWarnings =
    validation !== null &&
    (validation.errors.length > 0 || validation.warnings.length > 0);
```

with `isValid` where it used `is_valid`.

`ReactionNodeValidationResult.tsx`:

```tsx
export function ReactionNodeValidationResult({
  pathComponents,
}: Readonly<ReactionNodeValidationResultProps>) {
  // Templates carry no validation; a reaction not yet loaded has none either.
  const validation = useReactionSnapshot()?.validation;
  if (!validation) {
    return null;
  }
  return (
    <ReactionNodeValidationResultDisplay
      pathComponents={pathComponents}
      validation={validation}
    />
  );
}
```

`ReactionHeader.tsx`: `<ReactionValidationResult />` and `<ReactionPreview ref={previewRef} />`
(B5 rewrites the rest of the header).

- [ ] **Step 5: A provider around every preview outside the reaction page**

`DatasetReactionCard.tsx`: the exported card provides its reaction and the inner parts
read the snapshot.

```tsx
const CARD_SLOTS: ReactionSlots = {
  ViewDeleteButtons: ReactionViewButton,
  ValueLabel: DatasetReactionValueLabel,
  ViewOnlyLabel: DatasetReactionValueLabel,
};

export function DatasetReactionCard({
  reactionId,
  index,
}: Readonly<DatasetReactionCardProps>) {
  const source = useReduxReactionSource(reactionId);
  // The card only displays the reaction; its edit actions live in ReactionHeaderActions.
  return (
    <ReactionProvider
      reactionId={reactionId}
      source={source}
      slots={CARD_SLOTS}
    >
      <DatasetReactionCardBody
        reactionId={reactionId}
        index={index}
      />
    </ReactionProvider>
  );
}

function DatasetReactionCardBody({
  reactionId,
  index,
}: Readonly<DatasetReactionCardProps>) {
  const previewRef = useRef<HTMLDivElement | null>(null);
  const isValid = useReactionSnapshot()?.is_valid ?? false;
  return (
    <ReactionCard
      previewRef={previewRef}
      isInvalid={!isValid}
      actions={
        <ReactionHeaderActions
          reactionId={reactionId}
          previewRef={previewRef}
        />
      }
      title={
        <ReactionTitle
          index={index}
          id={reactionId}
        />
      }
    />
  );
}
```

`ReactionTitle` reads `const snapshot = useReactionSnapshot();` and uses
`snapshot?.pb_reaction_id ?? ''` and `snapshot?.is_valid` in place of the store read.
The slots are never rendered inside a card; `ReactionSlots` requires them, so the card
passes the view-only set. `ReactionHeaderActions` keeps its own store reads: it is the
editor's card action set.

`TemplatesList.page.tsx`: wrap each card.

```tsx
                {templatesOrder.map((templateId, index) => (
                  <TemplateReactionProvider
                    key={templateId}
                    templateId={templateId}
                  >
                    <ReactionCard
                      actions={<TemplateHeaderActions templateId={templateId} />}
                      title={
                        <TemplateTitle
                          index={index + 1}
                          templateId={templateId}
                        />
                      }
                    />
                  </TemplateReactionProvider>
                ))}
```

`TemplateTitle` keeps reading `template.name` from the store; names are not in the
snapshot and the title is editor code.

`EnumerationSetup.tsx`: the preview shows the template the form selects, not the page's:

```tsx
          {template && (
            <TemplateReactionProvider templateId={form.values.templateId}>
              <ReactionPreview />
            </TemplateReactionProvider>
          )}
```

(If `form.values.templateId` is typed as possibly undefined, narrow it the way the
existing `selectReactionById(form.values.templateId)` call does.)

`TemplateHeader.tsx`: `<ReactionPreview />` — the template page's provider already
supplies its template.

- [ ] **Step 6: Run the tests, the type check, and lint**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
grep -rn "selectReactionById\|selectOrderedInputsWrapper\|selectPreviewsByIdsWrapper\|selectReactionPartByPath" \
  apps/editor/src/common/components apps/editor/src/features/reactions/ReactionHeader/ReactionValidationResult \
  apps/editor/src/features/reactions/ReactionInteractions/ReactionNodeValidationResult
```

Expected: all tests pass (B3's count plus the five new test cases); clean type check and
lint; the grep prints nothing.

- [ ] **Step 7: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/common/components/ReactionPreview \
  frontend/apps/editor/src/common/components/ReactionCard \
  frontend/apps/editor/src/features/reactions/ReactionList/DatasetReactionCard \
  frontend/apps/editor/src/features/reactions/ReactionHeader \
  frontend/apps/editor/src/features/reactions/ReactionInteractions/ReactionNodeValidationResult \
  frontend/apps/editor/src/features/reactions/useReduxReactionSource.ts \
  frontend/apps/editor/src/features/templates \
  frontend/apps/editor/src/features/enumeration/EnumerationSetup/EnumerationSetup.tsx \
  frontend/apps/editor/src/pages
git commit -F "$SCRATCH/b4-msg.txt"   # "Read previews, cards, and validation through the provider"
```

### Task B5: The header reads the snapshot; its editor actions become props

The shared header shows the validation badge, the ORD ID, "Copy reaction image", and the
preview. Remove, Save as Template, Download, the copy-link menu, and rename are editor
features and arrive as props from an editor wrapper.

**Files:**

- Modify: `features/reactions/ReactionHeader/ReactionHeader.tsx`
- Create: `features/reactions/ReactionHeader/DatasetReactionHeader/DatasetReactionHeader.tsx`
- Create tests: `ReactionHeader.test.tsx`, `DatasetReactionHeader/DatasetReactionHeader.test.tsx`
- Modify: `pages/ReactionPage/ReactionPage.tsx`

**Interfaces:**

- Produces:
  - `ReactionHeader({ actions?: ReactNode; titleActions?: ReactNode })`: `actions` sit
    right of the validation badge; `titleActions` sit after the title.
  - `DatasetReactionHeader({ datasetId: number; reactionId: number })`: the reaction
    page's header, with the editor's actions.

- [ ] **Step 1: Write the failing tests**

`features/reactions/ReactionHeader/ReactionHeader.test.tsx`:

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { ReactionHeader } from './ReactionHeader.tsx';

describe('ReactionHeader', () => {
  it('shows the reaction ID, the actions it is given, and the preview', () => {
    const { getByRole, getByText } = renderInReactionView(
      <ReactionHeader
        actions={<button type="button">Page action</button>}
        titleActions={<button type="button">Title action</button>}
      />,
      { record: { pb_reaction_id: 'ord-123', is_valid: true, validation: null } },
    );
    expect(getByRole('heading', { name: 'ord-123' })).toBeInTheDocument();
    expect(getByText('Page action')).toBeInTheDocument();
    expect(getByText('Title action')).toBeInTheDocument();
    expect(getByText('Copy reaction image')).toBeInTheDocument();
    expect(getByText('There are no Inputs and Outcomes yet')).toBeInTheDocument();
  });
});
```

`DatasetReactionHeader/DatasetReactionHeader.test.tsx`:

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { DatasetReactionHeader } from './DatasetReactionHeader.tsx';

const record = { pb_reaction_id: 'ord-123', is_valid: true, validation: null };

describe('DatasetReactionHeader', () => {
  it('offers Remove and rename only when the reaction is editable', () => {
    const editable = renderInReactionView(
      <DatasetReactionHeader datasetId={2} reactionId={1} />,
      { record },
    );
    expect(editable.getByText('Remove')).toBeInTheDocument();
    expect(editable.getByText('Save as Template')).toBeInTheDocument();
    expect(editable.getByText('Download Reaction')).toBeInTheDocument();
    editable.unmount();

    const readOnly = renderInReactionView(
      <DatasetReactionHeader datasetId={2} reactionId={1} />,
      { record, isViewOnly: true },
    );
    expect(readOnly.queryByText('Remove')).not.toBeInTheDocument();
    expect(readOnly.getByText('Save as Template')).toBeInTheDocument();
  });
});
```

Match the Remove control's accessible text to what `RemoveReaction` renders (read it
first). Run:

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/ReactionHeader
```

Expected: FAIL — `DatasetReactionHeader` does not exist; `ReactionHeader` requires
`datasetId` and `reactionId`.

- [ ] **Step 2: Split the header**

`ReactionHeader.tsx` keeps the layout and the shared parts:

```tsx
interface ReactionHeaderProps {
  /** Controls beside the validation badge, such as remove and download. */
  actions?: ReactNode;
  /** Controls after the reaction's ID, such as copy and rename. */
  titleActions?: ReactNode;
}

export function ReactionHeader({ actions, titleActions }: Readonly<ReactionHeaderProps>) {
  const pbReactionId = useReactionSnapshot()?.pb_reaction_id;
  const previewRef = useRef<HTMLDivElement | null>(null);
  const onPreviewSave = useCallback(() => {
    copyPreviewAsImage(previewRef.current);
  }, []);
  return (
    <>
      <Flex
        justify="space-between"
        align="flex-end"
      >
        <ReactionValidationResult />
        <Flex
          align="center"
          gap="sm"
        >
          {actions}
        </Flex>
      </Flex>
      <Paper
        radius="md"
        p="lg"
      >
        {/* the existing Flex column: Title {pbReactionId}, then {titleActions},
            then the "Copy reaction image" button and <ReactionPreview ref={previewRef} /> */}
      </Paper>
    </>
  );
}
```

Write out the Paper's contents from today's file, putting `{titleActions}` where
`<CopyButton …/>` and the rename `ActionIcon` were. Remove from this file everything that
needs the store, wouter, `domain`, `RemoveReaction`, `SaveAsTemplate`, `DownloadMenu`,
`InputModal`, and the rename slice.

`DatasetReactionHeader/DatasetReactionHeader.tsx` holds what was removed:

```tsx
interface DatasetReactionHeaderProps {
  datasetId: number;
  reactionId: number;
}

/** The reaction page's header, with the editor's actions on a dataset reaction. */
export function DatasetReactionHeader({
  datasetId,
  reactionId,
}: Readonly<DatasetReactionHeaderProps>) {
  const [location] = useLocation();
  const { base } = useRouter();
  const dispatch = useAppDispatch();
  const isViewOnly = useIsViewOnly();
  const pbReactionId = useReactionSnapshot()?.pb_reaction_id ?? '';
  const isRenameOpened = useSelector(selectIsReactionRenameOpened);
  const [
    saveAsTemplateOpened,
    { open: openSaveAsTemplate, close: closeSaveAsTemplate },
  ] = useDisclosure();
  // onRenameOpen, onRenameClose, onReactionNameChange, and copyOptions exactly as they
  // were in ReactionHeader, with pbReactionId for reaction.pb_reaction_id.
  return (
    <>
      <ReactionHeader
        actions={
          <>
            {!isViewOnly && <RemoveReaction reactionId={reactionId} />}
            {/* the Save as Template Button and the DownloadMenu, as they were */}
          </>
        }
        titleActions={
          <>
            <CopyButton options={copyOptions} />
            {!isViewOnly && (
              <ActionIcon variant="transparent">
                <EditIcon onClick={onRenameOpen} />
              </ActionIcon>
            )}
          </>
        }
      />
      {saveAsTemplateOpened && (
        <SaveAsTemplate
          reactionId={reactionId}
          reactionPbId={pbReactionId}
          onClose={closeSaveAsTemplate}
        />
      )}
      {isRenameOpened && (
        <InputModal
          onClose={onRenameClose}
          onSubmit={onReactionNameChange}
          title="Edit Reaction ID"
          inputLabel="Reaction ID"
          initialValue={pbReactionId}
          stayOpenedOnSubmit
        />
      )}
    </>
  );
}
```

Copy the button, menu, and callback code from today's `ReactionHeader.tsx` verbatim
rather than retyping it; the comments above mark where each piece goes.
`SaveAsTemplate` and the rename modal are modals, so rendering them beside the header
instead of inside its `Paper` does not move them on screen.

`ReactionPage.tsx`: render `<DatasetReactionHeader datasetId={datasetId} reactionId={reactionId} />`
in place of `<ReactionHeader … />`.

- [ ] **Step 3: Run the tests, then jscpd**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/ReactionHeader src/pages
cd ~/ord/ord-app && frontend/node_modules/.bin/jscpd --config .jscpd.json
```

Expected: PASS. jscpd may now pair `DatasetReactionHeader`'s download menu with
`ReactionHeaderActions`' (the card's), as it may have paired `ReactionHeader` with it
before. If it reports a new clone, extract the shared `DownloadMenu` element into
`features/reactions/ReactionHeader/ReactionDownloadMenu.tsx`
(`({ datasetId, reactionId, className? })`) and use it in both.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/ReactionHeader frontend/apps/editor/src/pages/ReactionPage/ReactionPage.tsx
git commit -F "$SCRATCH/b5-msg.txt"   # "Pass the reaction header's editor actions in as props"
```

### Task B6: The crude component's reaction link is a slot

`CrudeComponentView` dispatches `searchReaction`, which looks the ORD ID up in the active
dataset and navigates to an editor route. Another app links differently, so the link
becomes an optional slot; without one the ID is plain text.

**Files:**

- Modify: `features/reactions/provider/reactionProvider.types.ts` (`ReactionLink` slot)
- Modify: `features/reactions/ReactionView/CrudeComponentView/CrudeComponentView.tsx`
- Create: `features/reactions/ReactionInteractions/SearchReactionLink/SearchReactionLink.tsx`
- Modify: `pages/ReactionPage/useDatasetReactionProviderProps.ts`,
  `features/templates/TemplateReactionProvider/templateReactionSlots.ts`
- Modify test: `CrudeComponentView.test.tsx`
- Create test: `SearchReactionLink.test.tsx`

**Interfaces:**

- Produces:
  - `interface ReactionLinkProps { pbReactionId: string }` and the optional slot
    `ReactionSlots.ReactionLink?: FC<ReactionLinkProps>` in `reactionProvider.types.ts`.
  - `SearchReactionLink(props: ReactionLinkProps)` in the editor: today's anchor.

- [ ] **Step 1: Write the failing tests**

`CrudeComponentView.test.tsx`:

```tsx
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import type { ReactionLinkProps } from 'features/reactions/provider/reactionProvider.types.ts';
import type { ReactionCrudeComponent } from 'store/entities/reactions/reactionsInputs/reactionInputs.types.ts';
import { CrudeComponentView } from './CrudeComponentView.tsx';

const crude = { reactionId: 'rxn-123' } as ReactionCrudeComponent;

function TestLink({ pbReactionId }: Readonly<ReactionLinkProps>) {
  return <a href={`/reactions/${pbReactionId}`}>{pbReactionId}</a>;
}

describe('CrudeComponentView', () => {
  it('links the reaction through the host app’s link slot', () => {
    const { getByRole } = renderInReactionView(<CrudeComponentView crudeComponent={crude} />, {
      slots: { ReactionLink: TestLink },
    });
    expect(getByRole('link', { name: 'rxn-123' })).toHaveAttribute('href', '/reactions/rxn-123');
  });

  it('shows the reaction ID as text when the host supplies no link', () => {
    const { getByText, queryByRole } = renderInReactionView(
      <CrudeComponentView crudeComponent={crude} />,
    );
    expect(getByText('rxn-123')).toBeInTheDocument();
    expect(queryByRole('link')).not.toBeInTheDocument();
  });
});
```

`features/reactions/ReactionInteractions/SearchReactionLink/SearchReactionLink.test.tsx`
carries today's assertion over from `CrudeComponentView.test.tsx`:

```tsx
import { fireEvent } from '@testing-library/react';
import { renderWithProviders } from 'test/renderWithProviders.tsx';
import { SearchReactionLink } from './SearchReactionLink.tsx';

const searchReaction = vi.fn((id: string) => ({
  type: 'reactions/searchReaction/mock',
  payload: id,
}));
vi.mock('store/entities/reactions/reactions.thunks.ts', async importActual => ({
  ...((await importActual()) as Record<string, unknown>),
  searchReaction: (id: string) => searchReaction(id),
}));

describe('SearchReactionLink', () => {
  it('searches the dataset for the reaction when clicked', () => {
    const { getByText } = renderWithProviders(<SearchReactionLink pbReactionId="rxn-123" />);
    fireEvent.click(getByText('rxn-123'));
    expect(searchReaction).toHaveBeenCalledWith('rxn-123');
  });
});
```

Copy the mock's exact form from today's `CrudeComponentView.test.tsx`. Run:

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/features/reactions/ReactionView/CrudeComponentView src/features/reactions/ReactionInteractions/SearchReactionLink
```

Expected: FAIL — the slot type and `SearchReactionLink` do not exist.

- [ ] **Step 2: The slot**

In `reactionProvider.types.ts`:

```ts
export interface ReactionLinkProps {
  /** The linked reaction's ORD ID. */
  pbReactionId: string;
}

/** Components the host app supplies for the parts of the view it owns. */
export interface ReactionSlots {
  ViewDeleteButtons: FC<ReactionViewDeleteButtonsProps>;
  ValueLabel: FC<ReactionValueLabelProps>;
  ViewOnlyLabel: FC<ReactionValueLabelProps>;
  /** Links another reaction by its ORD ID; without it the ID shows as text. */
  ReactionLink?: FC<ReactionLinkProps>;
}
```

`CrudeComponentView.tsx`:

```tsx
export function CrudeComponentView({
  crudeComponent,
}: Readonly<CrudeComponentViewProps>) {
  const { ReactionLink } = useReactionSlots();
  const pbReactionId = crudeComponent.reactionId ?? '';
  return ReactionLink ? <ReactionLink pbReactionId={pbReactionId} /> : <span>{pbReactionId}</span>;
}
```

`SearchReactionLink.tsx`:

```tsx
import { Anchor } from '@mantine/core';
import type { ReactionLinkProps } from 'features/reactions/provider/reactionProvider.types.ts';
import { searchReaction } from 'store/entities/reactions/reactions.thunks.ts';
import { useAppDispatch } from 'store/useAppDispatch.ts';

/** Finds the reaction in the active dataset and opens its page. */
export function SearchReactionLink({ pbReactionId }: Readonly<ReactionLinkProps>) {
  const dispatch = useAppDispatch();
  const onClick = () => {
    dispatch(searchReaction(pbReactionId));
  };
  return <Anchor onClick={onClick}>{pbReactionId}</Anchor>;
}
```

Add `ReactionLink: SearchReactionLink` to `EDITABLE_SLOTS` (so `VIEW_ONLY_SLOTS`, which
spreads it, has it too) and to `TEMPLATE_SLOTS`. The template page keeps today's
behavior, which searches the active dataset; see Notes.

- [ ] **Step 3: Run the tests**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider/reactionProvider.types.ts \
  frontend/apps/editor/src/features/reactions/ReactionView/CrudeComponentView \
  frontend/apps/editor/src/features/reactions/ReactionInteractions/SearchReactionLink \
  frontend/apps/editor/src/pages/ReactionPage/useDatasetReactionProviderProps.ts \
  frontend/apps/editor/src/features/templates/TemplateReactionProvider/templateReactionSlots.ts
git commit -F "$SCRATCH/b6-msg.txt"   # "Link a crude component's reaction through a slot"
```

### Task B7: The contract suite renders the full reaction over both sources

The design's contract: the same snapshot gives the same output from either source. With
the full-reaction fixture, every section and the preview render over a static source
and over the Redux source; the HTML must match. The static case's store holds no
reaction, so a component that still reads the store renders differently and fails.

**Files:**

- Create: `test/fullReactionSnapshot.ts`
- Create: `store/entities/reactions/reactionSourceContract.test.tsx`

**Interfaces:**

- Produces: `fullReactionSnapshot(): ReactionSnapshot` (D3 reuses it), and in the test
  file a `renderOverBothSources(ui)` helper that D3 extends.

- [ ] **Step 1: The fixture**

`test/fullReactionSnapshot.ts`:

```ts
import type { ReactionSnapshot } from 'features/reactions/provider/reactionProvider.types.ts';
import { ordReactionToReaction } from 'store/entities/reactions/reactions.converters.ts';
import { fullReaction } from './fullReaction.ts';

/** The full-reaction fixture as a stored dataset reaction, valid and with no previews. */
export function fullReactionSnapshot(): ReactionSnapshot {
  return {
    data: ordReactionToReaction(fullReaction),
    previews: {},
    summary: { provenance: {}, summary: {}, conditions: '' },
    pb_reaction_id: 'ord-full',
    is_valid: true,
    validation: null,
  };
}
```

If the reducer links entities on load (`linkReactionEntities` in
`reactions.reducer.ts`), apply the same function here so the fixture matches what the
store holds after a load.

- [ ] **Step 2: The contract test**

`store/entities/reactions/reactionSourceContract.test.tsx`:

```tsx
import { MantineProvider } from '@mantine/core';
import { configureStore } from '@reduxjs/toolkit';
import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { Provider } from 'react-redux';
import { ReactionPreview } from 'common/components/ReactionPreview/ReactionPreview.tsx';
import { ReactionContent } from 'features/reactions/ReactionEntities/ReactionTabs/ReactionContent.tsx';
import { ReactionProvider } from 'features/reactions/provider/ReactionProvider.tsx';
import type {
  ReactionSlots,
  ReactionSource,
} from 'features/reactions/provider/reactionProvider.types.ts';
import { createStaticReactionSource } from 'features/reactions/provider/staticReactionSource.ts';
import type { AppState } from 'store/configureAppStore.ts';
import { rootReducer } from 'store/rootReducer.ts';
import { fullReactionSnapshot } from 'test/fullReactionSnapshot.ts';
import { reduxReactionSource } from './reduxReactionSource.ts';

const Empty = () => null;
const slots: ReactionSlots = { ViewDeleteButtons: Empty, ValueLabel: Empty, ViewOnlyLabel: Empty };

/** React's useId output differs between two mounts; nothing else may. */
const normalizeIds = (html: string) => html.replaceAll(/«r[0-9a-z]+»|:r[0-9a-z]+:/g, 'ID');

function renderOver(source: ReactionSource, store: ReturnType<typeof makeStore>, ui: ReactElement) {
  function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return (
      <Provider store={store}>
        <MantineProvider>
          <ReactionProvider
            reactionId={1}
            source={source}
            slots={slots}
          >
            {children}
          </ReactionProvider>
        </MantineProvider>
      </Provider>
    );
  }
  const { container, unmount } = render(ui, { wrapper: Wrapper });
  const html = normalizeIds(container.innerHTML);
  unmount();
  return html;
}

function makeStore(withReaction: boolean) {
  return configureStore({
    reducer: rootReducer,
    preloadedState: withReaction
      ? ({
          entities: { reactions: { reactionsById: { 1: { id: 1, ...fullReactionSnapshot() } } } },
        } as unknown as AppState)
      : undefined,
  });
}

/** Renders `ui` over a static source (empty store) and over the Redux source (seeded store). */
export function renderOverBothSources(ui: ReactElement): [string, string] {
  const emptyStore = makeStore(false);
  const seededStore = makeStore(true);
  return [
    renderOver(createStaticReactionSource(fullReactionSnapshot()), emptyStore, ui),
    renderOver(reduxReactionSource(seededStore, 1), seededStore, ui),
  ];
}

describe('the reaction view over either source', () => {
  it.each([
    ['every section', <ReactionContent key="content" viewMode="list" />],
    ['the preview', <ReactionPreview key="preview" />],
  ])('renders %s the same', (_name, ui) => {
    const [overStatic, overRedux] = renderOverBothSources(ui);
    expect(overStatic).toBe(overRedux);
    expect(overStatic.length).toBeGreaterThan(0);
  });
});
```

Vitest test files cannot export to other test files cleanly; if the export trips the
`react-refresh/only-export-components` lint or Vitest, move `renderOverBothSources`
and `makeStore` into `test/renderOverBothSources.tsx` (test-only helper, with the same
eslint comment `renderInReactionView.tsx` carries) and import it here and in D3.

- [ ] **Step 3: Run it**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/store/entities/reactions/reactionSourceContract.test.tsx
```

Expected: PASS. If it fails, diff the two HTML strings
(`expect(overStatic).toBe(overRedux)` prints the diff): an element present only in the
Redux render means a component below still reads `reactionsById` from the store. Fix the
component, not the test. If useId output takes a form the regex misses, widen the
regex to that form only.

- [ ] **Step 4: Prove the test can fail**

Temporarily change `Notes.tsx` back to
`useSelector(selectReactionPartByPath(1, ['notes']))`, run the test, and confirm it fails
on the static case; restore the hook.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/test/fullReactionSnapshot.ts \
  frontend/apps/editor/src/store/entities/reactions/reactionSourceContract.test.tsx
git commit -F "$SCRATCH/b7-msg.txt"   # "Check that the reaction view renders the same over both sources"
```

### Task B8: Documentation of the slots

**Files:**

- Modify: `.claude/skills/ord-app-ui-testing/SKILL.md` (render helpers section)

- [ ] **Step 1: Describe the harness**

Where the skill describes `renderInReactionView`, say that it mounts `ReactionProvider`
over a Redux source, that the reaction is editable unless `isViewOnly` is set, that a
string `reactionId` renders a template, and that `record` sets stored fields such as
`pb_reaction_id` and `validation`. One short paragraph.

- [ ] **Step 2: Commit**

```bash
cd ~/ord/ord-app
git add .claude/skills/ord-app-ui-testing/SKILL.md
git commit -F "$SCRATCH/b8-msg.txt"   # "Describe the reaction view test harness"
```

### Task B9: Open PR B

- [ ] **Step 1: Full check**

```bash
cd ~/ord/ord-app/frontend
npm run lint:check && npm run typecheck && npm run test:coverage && npm run build
cd .. && frontend/node_modules/.bin/jscpd --config .jscpd.json
```

Expected: all green; the editor's coverage floors hold.

- [ ] **Step 2: Local Playwright**

With the e2e stack up, `cd frontend/apps/editor && npx playwright test`. Expected: PASS
(screenshots skipped locally).

- [ ] **Step 3: Push, write the body, mark ready**

```bash
cd ~/ord/ord-app && git push
gh pr edit --body-file "$SCRATCH/b-body.md"
gh pr ready
```

The body: Summary (display reads go through the provider; every preview sits under a
provider; header actions and the crude-component link are editor-supplied). Changes (one
bullet per task). Testing (Vitest counts, the contract suite, the three screenshots in
CI). Notes:

- Changed assertions: none. `OpenSingleEntityButton.test.tsx` and
  `ReactionCard.test.tsx` were smoke tests and now assert labels and content;
  `CrudeComponentView`'s click assertion moved to `SearchReactionLink.test.tsx` with the
  code it tests.
- The template page's crude-component link searches the active dataset, as it did
  before; that dataset is unrelated to the template. Unchanged here.
- `ReactionCard` now requires a provider; `DatasetReactionCard`,
  `TemplateReactionProvider`, and `EnumerationSetup` supply one.

---

## PR C: the drawer's stack lives in the provider

Branch `reaction-drawer-state`, from `main` after B merges. The stack of open drawer
forms (`features.reactionForm`) becomes a reducer inside `ReactionProvider`, read and
changed through `useDrawerStack()` and `useDrawer()`. The provider is keyed by reaction,
so the stack starts empty for each reaction.

Thirteen files write the stack, not the four the design names, and one other slice
(`variablesSidebar`) reacts to its actions. Paths are relative to
`frontend/apps/editor/src/`.

### Task C1: The drawer reducer and its hooks

**Files:**

- Create: `features/reactions/provider/drawer.ts`, `features/reactions/provider/drawer.test.ts`
- Modify: `features/reactions/provider/reactionProvider.context.ts`,
  `ReactionProvider.tsx`, `reactionProvider.hooks.ts`, `reactionProvider.hooks.test.tsx`

**Interfaces:**

- Produces (in `drawer.ts`):

  ```ts
  /** Open drawer forms, bottom first; the last one is the visible form. */
  export type DrawerStack = ReadonlyArray<ReactionPathComponents>;
  export interface DrawerActions {
    /** Replaces the stack, for example with the chain of entities leading to a field. */
    set(stack: ReadonlyArray<ReactionPathComponents>): void;
    push(pathComponents: ReactionPathComponents): void;
    pop(): void;
    /** Keeps the entries up to and including `index`. */
    truncate(index: number): void;
    clear(): void;
  }
  export function drawerReducer(stack: DrawerStack, action: DrawerAction): DrawerStack;
  export function createDrawerActions(dispatch: Dispatch<DrawerAction>): DrawerActions;
  export const EMPTY_DRAWER_STACK: DrawerStack;
  ```

- Produces (hooks): `useDrawerStack(): DrawerStack` and `useDrawer(): DrawerActions`.
  `useDrawer()` returns the same object for the life of the provider, and a component
  that calls only `useDrawer()` does not re-render when the stack changes.

- [ ] **Step 1: Branch**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c reaction-drawer-state
cd frontend && npm ci
```

- [ ] **Step 2: Write the failing reducer test**

`features/reactions/provider/drawer.test.ts`, ported from
`store/features/reactionForm/reactionForm.reducer.test.ts`:

```ts
import { drawerReducer, EMPTY_DRAWER_STACK } from './drawer.ts';

describe('drawerReducer', () => {
  it('replaces the stack with set', () => {
    expect(drawerReducer(EMPTY_DRAWER_STACK, { type: 'set', stack: [['inputs', 0]] })).toEqual([
      ['inputs', 0],
    ]);
  });

  it('appends with push', () => {
    const stack = drawerReducer([['a']], { type: 'push', pathComponents: ['b', 1] });
    expect(stack).toEqual([['a'], ['b', 1]]);
  });

  it('drops the last entry with pop, and leaves an empty stack empty', () => {
    expect(drawerReducer([['a'], ['b'], ['c']], { type: 'pop' })).toEqual([['a'], ['b']]);
    expect(drawerReducer(EMPTY_DRAWER_STACK, { type: 'pop' })).toEqual([]);
  });

  it('keeps the entries up to the index, inclusive, with truncate', () => {
    const stack = drawerReducer([['a'], ['b'], ['c'], ['d']], { type: 'truncate', index: 1 });
    expect(stack).toEqual([['a'], ['b']]);
  });

  it('empties the stack with clear', () => {
    expect(drawerReducer([['a']], { type: 'clear' })).toBe(EMPTY_DRAWER_STACK);
  });
});
```

Run: `cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/provider/drawer.test.ts`.
Expected: FAIL — `./drawer.ts` does not exist.

- [ ] **Step 3: The reducer**

`features/reactions/provider/drawer.ts`:

```ts
import type { Dispatch } from 'react';
import type { ReactionPathComponents } from 'common/types/reaction/reactionPathComponents.ts';

/** Open drawer forms, bottom first; the last one is the visible form. */
export type DrawerStack = ReadonlyArray<ReactionPathComponents>;

export type DrawerAction =
  | { type: 'set'; stack: ReadonlyArray<ReactionPathComponents> }
  | { type: 'push'; pathComponents: ReactionPathComponents }
  | { type: 'pop' }
  | { type: 'truncate'; index: number }
  | { type: 'clear' };

export interface DrawerActions {
  /** Replaces the stack, for example with the chain of entities leading to a field. */
  set(stack: ReadonlyArray<ReactionPathComponents>): void;
  push(pathComponents: ReactionPathComponents): void;
  pop(): void;
  /** Keeps the entries up to and including `index`. */
  truncate(index: number): void;
  clear(): void;
}

export const EMPTY_DRAWER_STACK: DrawerStack = [];

export function drawerReducer(stack: DrawerStack, action: DrawerAction): DrawerStack {
  switch (action.type) {
    case 'set':
      return action.stack;
    case 'push':
      return [...stack, action.pathComponents];
    case 'pop':
      return stack.slice(0, -1);
    case 'truncate':
      return stack.slice(0, action.index + 1);
    case 'clear':
      return EMPTY_DRAWER_STACK;
  }
}

/** The drawer's operations over a reducer's dispatch, which React keeps stable. */
export function createDrawerActions(dispatch: Dispatch<DrawerAction>): DrawerActions {
  return {
    set: stack => dispatch({ type: 'set', stack }),
    push: pathComponents => dispatch({ type: 'push', pathComponents }),
    pop: () => dispatch({ type: 'pop' }),
    truncate: index => dispatch({ type: 'truncate', index }),
    clear: () => dispatch({ type: 'clear' }),
  };
}
```

Run the test again. Expected: PASS.

- [ ] **Step 4: Write the failing hook tests**

In `reactionProvider.hooks.test.tsx`, import `act`, `useDrawer`, `useDrawerStack`, and add:

```tsx
describe('the drawer', () => {
  const wrapper = wrapperFor(createStaticReactionSource(snapshot));

  it('opens forms and keeps the same actions across renders', () => {
    const { result, rerender } = renderHook(
      () => ({ stack: useDrawerStack(), drawer: useDrawer() }),
      { wrapper },
    );
    const { drawer } = result.current;
    act(() => drawer.push(['notes']));
    rerender();
    expect(result.current.stack).toEqual([['notes']]);
    expect(result.current.drawer).toBe(drawer);
  });

  it('does not re-render a component that only changes the stack', () => {
    let renders = 0;
    const { result } = renderHook(
      () => {
        renders += 1;
        return useDrawer();
      },
      { wrapper },
    );
    const rendersAfterMount = renders;
    act(() => result.current.push(['notes']));
    expect(renders).toBe(rendersAfterMount);
  });

  it('starts empty under a provider for another reaction', () => {
    const source = createStaticReactionSource(snapshot);
    function Keyed({ id, children }: Readonly<{ id: number; children: ReactNode }>) {
      return (
        <ReactionProvider key={id} reactionId={id} source={source} slots={slots}>
          {children}
        </ReactionProvider>
      );
    }
    let id = 1;
    function KeyedWrapper({ children }: Readonly<{ children: ReactNode }>) {
      return <Keyed id={id}>{children}</Keyed>;
    }
    const { result, rerender } = renderHook(
      () => ({ stack: useDrawerStack(), drawer: useDrawer() }),
      { wrapper: KeyedWrapper },
    );
    act(() => result.current.drawer.push(['notes']));
    expect(result.current.stack).toHaveLength(1);
    id = 2;
    rerender();
    expect(result.current.stack).toEqual([]);
  });
});
```

Run the hooks test. Expected: FAIL — `useDrawer` and `useDrawerStack` are not exported.

- [ ] **Step 5: Contexts, provider, hooks**

`reactionProvider.context.ts`, beside `reactionProviderContext`:

```ts
/** The drawer's stack, apart from its actions so writers do not re-render on each change. */
export const drawerStackContext = createContext<DrawerStack | null>(null);

export const drawerActionsContext = createContext<DrawerActions | null>(null);
```

`ReactionProvider.tsx`, inside the component before `return`:

```tsx
  const [drawerStack, dispatchDrawer] = useReducer(drawerReducer, EMPTY_DRAWER_STACK);
  const drawer = useMemo(() => createDrawerActions(dispatchDrawer), []);
```

and wrap the children, inside the two existing providers:

```tsx
        <drawerActionsContext.Provider value={drawer}>
          <drawerStackContext.Provider value={drawerStack}>
            {children}
          </drawerStackContext.Provider>
        </drawerActionsContext.Provider>
```

Add to the doc comment: "Its drawer stack lives as long as it does; give it a `key` per
reaction so the stack starts empty for each one."

`reactionProvider.hooks.ts`:

```ts
const OUTSIDE_PROVIDER = 'Reaction hooks must be used inside a ReactionProvider.';

/** The forms open in the drawer, bottom first. */
export function useDrawerStack(): DrawerStack {
  const stack = useContext(drawerStackContext);
  if (stack === null) {
    throw new Error(OUTSIDE_PROVIDER);
  }
  return stack;
}

/** Opens and closes drawer forms; the same object for the life of the provider. */
export function useDrawer(): DrawerActions {
  const drawer = useContext(drawerActionsContext);
  if (drawer === null) {
    throw new Error(OUTSIDE_PROVIDER);
  }
  return drawer;
}
```

and use `OUTSIDE_PROVIDER` in `useProviderValue`'s throw too.

Run the provider tests:

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/provider
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider
git commit -F "$SCRATCH/c1-msg.txt"   # "Hold the drawer's stack in ReactionProvider"
```

### Task C2: Key the providers by reaction

wouter's `Switch` clones the route element without a key, so moving from one reaction to
another keeps the same `ReactionPage`, and with it the provider and its stack.

**Files:**

- Modify: `pages/ReactionPage/ReactionPage.tsx`
- Create: `pages/ReactionPage/ReactionPage.test.tsx`

**Interfaces:**

- Consumes: `useDrawer`, `useDrawerStack` (C1); `TemplateReactionProvider` is keyed
  already (B4).

- [ ] **Step 1: Write the failing test**

`pages/ReactionPage/ReactionPage.test.tsx` renders the page for one reaction, opens the
drawer through a probe, rerenders for another reaction, and expects an empty stack. Mock
the heavy children so the test exercises only the page's provider:

```tsx
import { act } from '@testing-library/react';
import type { ReactNode } from 'react';
import type { AppState } from 'store/configureAppStore.ts';
import { renderWithProviders } from 'test/renderWithProviders.tsx';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import { useDrawer, useDrawerStack } from 'features/reactions/provider/reactionProvider.hooks.ts';
import type { DrawerActions } from 'features/reactions/provider/drawer.ts';
import { ReactionPage } from './ReactionPage.tsx';

let drawer: DrawerActions | undefined;
function DrawerProbe() {
  drawer = useDrawer();
  return <span data-testid="stack">{useDrawerStack().length}</span>;
}

vi.mock('features/reactions/ReactionHeader/DatasetReactionHeader/DatasetReactionHeader.tsx', () => ({
  DatasetReactionHeader: () => <DrawerProbe />,
}));
vi.mock('features/reactions/ReactionEntities/ReactionTabs/ReactionContent.tsx', () => ({
  ReactionContent: () => null,
}));
vi.mock('features/reactions/ReactionDetailsSidebar/ReactionDetailsSidebar.tsx', () => ({
  ReactionDetailsSidebar: () => null,
}));
// The page shell's user menu needs Auth0 and the signed-in user; neither matters here.
vi.mock('common/components/PageContainer/PageContainer.tsx', () => ({
  PageContainer: ({ children }: Readonly<{ children: ReactNode }>) => <>{children}</>,
}));
vi.mock('store/entities/reactions/reactions.thunks.ts', async importActual => ({
  ...((await importActual()) as Record<string, unknown>),
  getReaction: () => ({ type: 'test/noop' }),
}));

const reaction = (id: number) => ({
  id,
  pb_reaction_id: `ord-${id}`,
  is_valid: true,
  validation: null,
  data: emptyReactionData(),
  previews: {},
  summary: { provenance: {}, summary: {}, conditions: '' },
});

describe('ReactionPage', () => {
  it('starts each reaction with the drawer closed', () => {
    const { getByTestId, rerender } = renderWithProviders(
      <ReactionPage datasetId={1} reactionId={2} />,
      {
        preloadedState: {
          entities: { reactions: { reactionsById: { 2: reaction(2), 3: reaction(3) } } },
        } as unknown as AppState,
      },
    );
    act(() => drawer?.push(['notes']));
    expect(getByTestId('stack')).toHaveTextContent('1');
    rerender(<ReactionPage datasetId={1} reactionId={3} />);
    expect(getByTestId('stack')).toHaveTextContent('0');
  });
});
```

`DrawerProbe` is defined above the mocks; Vitest hoists `vi.mock` factories, and a
factory may refer to a module-level function only if it is not called at hoist time,
which holds here because the factory returns a component. If Vitest still reports
"Cannot access 'DrawerProbe' before initialization", move the probe into a
`vi.hoisted(() => …)` block. If `renderWithProviders` does not return `rerender`, use the
result of `render` it wraps.

Run: `cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/pages/ReactionPage`.
Expected: FAIL — the stack still reads 1 after the rerender.

- [ ] **Step 2: Key the provider**

`ReactionPage.tsx`:

```tsx
      <ReactionProvider
        key={reactionId}
        {...providerProps}
      >
```

(`key` stays out of `useDatasetReactionProviderProps`: React warns when `key` arrives
inside a spread object.) Run the test. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/pages/ReactionPage
git commit -F "$SCRATCH/c2-msg.txt"   # "Key the reaction page's provider by reaction"
```

### Task C3: Every writer uses `useDrawer()`; delete `features.reactionForm`

**Files:**

- Modify: `features/reactions/ReactionDetailsSidebar/ReactionDetailsSidebar.tsx`
- Modify: `features/reactions/ReactionInteractions/ReactionViewDeleteButtons/reactionViewDeleteButtons.utils.ts`
- Modify: `features/reactions/ReactionHeader/ReactionValidationResult/ReactionValidationList.tsx`
- Modify: `features/templates/VariablesSidebar/VariablesSidebar.tsx`
- Modify: `features/reactions/ReactionEntities/ReactionEntityDelete/ReactionEntityDelete.tsx`
- Modify: `features/reactions/ReactionEntities/entityFormConfiguration/buildUseCreate.ts`
- Modify: `…/entityFormConfiguration/inputs/InputsComponentsList/InputsComponentList.tsx`,
  `…/outcomes/ProductComponentsList.tsx`, `…/workups/WorkupInput.tsx`
- Modify: `features/reactions/ReactionView/OpenSingleEntityButton/OpenSingleEntityButton.tsx`,
  `ReactionView/{Identifiers,Observation,Workups}/*.tsx`
- Modify: `store/features/features.reducer.ts`, `store/features/variablesSidebar/variablesSidebar.reducer.ts`
- Delete: `store/features/reactionForm/` (5 files)
- Modify tests: `reactionViewDeleteButtons.utils.test.ts`, `buildUseCreate.test.tsx`,
  `variablesSidebar.reducer.test.ts`, `VariablesSidebar.test.tsx`, and the harness of
  `ReactionEditDeleteButtons.test.tsx`, `ReactionSetVariablesButton.test.tsx`,
  `ReactionViewButton.test.tsx`, `ReactionEntityDelete.test.tsx`, `WorkupInput.test.tsx`,
  `ReactionValidationList.test.tsx`
- Create test: `features/reactions/ReactionDetailsSidebar/ReactionDetailsSidebar.test.tsx`

**Interfaces:**

- Consumes: `useDrawer()`, `useDrawerStack()` (C1).

- [ ] **Step 1: Move the harness of the smoke tests**

Each of `ReactionEditDeleteButtons.test.tsx`, `ReactionSetVariablesButton.test.tsx`,
`ReactionViewButton.test.tsx`, `ReactionEntityDelete.test.tsx`, `WorkupInput.test.tsx`,
and `ReactionValidationList.test.tsx` renders with `renderWithProviders`, which mounts no
provider. Switch each to `renderInReactionView` (same element, same assertions). For
`VariablesSidebar.test.tsx`, keep `renderWithProviders` and its preloaded state, and wrap
the element in the template's provider:

```tsx
      renderWithProviders(
        <TemplateReactionProvider templateId="template_1">
          <VariablesSidebar templateId="template_1" />
        </TemplateReactionProvider>,
        buildState(true),
      );
```

Run them: `npx vitest run src/features/reactions/ReactionInteractions src/features/reactions/ReactionEntities/ReactionEntityDelete src/features/reactions/ReactionEntities/entityFormConfiguration/workups src/features/reactions/ReactionHeader src/features/templates/VariablesSidebar`.
Expected: PASS (they pass with or without the provider today).

- [ ] **Step 2: Rewrite the tests that assert drawer dispatches**

`reactionViewDeleteButtons.utils.test.ts` → rename to `.test.tsx`. Drop the dispatch and
actions mocks; render the hook with the stack under a provider:

```tsx
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ReactionProvider } from 'features/reactions/provider/ReactionProvider.tsx';
import { useDrawerStack } from 'features/reactions/provider/reactionProvider.hooks.ts';
import { createStaticReactionSource } from 'features/reactions/provider/staticReactionSource.ts';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import type { ReactionViewDeleteButtonsProps } from './reactionViewDeleteButtons.types.ts';
import { useOnViewEdit } from './reactionViewDeleteButtons.utils.ts';

const Empty = () => null;
const source = createStaticReactionSource({
  data: emptyReactionData(),
  previews: {},
  summary: { provenance: {}, summary: {}, conditions: '' },
});

function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <ReactionProvider
      reactionId={1}
      source={source}
      slots={{ ViewDeleteButtons: Empty, ValueLabel: Empty, ViewOnlyLabel: Empty }}
    >
      {children}
    </ReactionProvider>
  );
}

function openWith(props: Omit<ReactionViewDeleteButtonsProps, 'entityName'>) {
  const { result } = renderHook(
    () => ({ open: useOnViewEdit(props), stack: useDrawerStack() }),
    { wrapper: Wrapper },
  );
  act(() => result.current.open());
  return result.current.stack;
}

describe('useOnViewEdit', () => {
  it('appends the path to the stack when there is no history', () => {
    expect(openWith({ pathComponents: ['inputs', 0] })).toEqual([['inputs', 0]]);
  });

  it('replaces the stack with the history plus the current path', () => {
    expect(
      openWith({
        pathComponents: ['inputs', 0],
        historyPathComponents: [['setup'], ['conditions']],
      }),
    ).toEqual([['setup'], ['conditions'], ['inputs', 0]]);
  });
});
```

Keep any other `describe` blocks in the file (for example
`onViewDeleteButtonsWrapperClick`) as they are.

`buildUseCreate.test.tsx`: keep the `useAppDispatch` and `addUpdateReactionField` mocks
(E changes those); delete the `reactionForm.actions.ts` mock. Replace the hand-built
`reactionContext.Provider` in its wrapper with
`<ReactionProvider reactionId={7} source={source} actions={actions} slots={slots}>`
(a static source as above, `actions = { update: vi.fn(), remove: vi.fn() }`), keeping
the inner `reactionEntityContext.Provider`. Read the stack in the same `renderHook`
(`() => ({ create: useCreate(), stack: useDrawerStack() })`), and replace each
`addReactionPathComponentToList` dispatch assertion with a stack assertion:

```ts
    expect(result.current.stack).toEqual([['inputs', 0, 'components', 'key1']]);
```

and in "does not open the sidebar when shouldOpenSidebar is false", keep
`expect(dispatch).toHaveBeenCalledTimes(1)` and add
`expect(result.current.stack).toEqual([]);`. Wrap each creation call in `act`.

`variablesSidebar.reducer.test.ts`: delete the case "closes when the reaction path
changes (set or add)" and its imports. The behavior moves to the component:

`VariablesSidebar.test.tsx`, a new case (give the fixture variable a real path, such as
`['notes', 'procedureDetails']`, and keep the existing cases passing with it):

```tsx
  it('closes and opens the variable’s entity in the reaction drawer when a variable is clicked', () => {
    function StackProbe() {
      return <span data-testid="stack">{JSON.stringify(useDrawerStack())}</span>;
    }
    const { getByText, queryByText, getByTestId } = renderWithProviders(
      <TemplateReactionProvider templateId="template_1">
        <VariablesSidebar templateId="template_1" />
        <StackProbe />
      </TemplateReactionProvider>,
      buildState(true),
    );
    fireEvent.click(getByText('@reagent'));
    expect(getByTestId('stack')).toHaveTextContent(
      JSON.stringify(reactionFlatPathToSidebars(['notes', 'procedureDetails'])),
    );
    expect(queryByText('@reagent')).not.toBeInTheDocument();
  });
```

If Mantine's Drawer keeps its content mounted during its close transition in happy-dom,
wait with `await waitFor(() => expect(queryByText('@reagent')).not.toBeInTheDocument())`.

`ReactionDetailsSidebar.test.tsx` (new; the drawer had no unit test):

```tsx
import { act, fireEvent, waitFor } from '@testing-library/react';
import { useDrawer } from 'features/reactions/provider/reactionProvider.hooks.ts';
import type { DrawerActions } from 'features/reactions/provider/drawer.ts';
import { renderInReactionView } from 'test/renderInReactionView.tsx';
import { ReactionDetailsSidebar } from './ReactionDetailsSidebar.tsx';

let drawer: DrawerActions;
function Probe() {
  drawer = useDrawer();
  return null;
}

describe('ReactionDetailsSidebar', () => {
  it('opens the pushed form and closes on Escape', async () => {
    const { getByRole, queryByRole } = renderInReactionView(
      <>
        <Probe />
        <ReactionDetailsSidebar reactionId={1} />
      </>,
    );
    expect(queryByRole('dialog')).not.toBeInTheDocument();
    act(() => drawer.push(['notes']));
    const dialog = getByRole('dialog');
    expect(dialog).toHaveTextContent('Notes');
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(queryByRole('dialog')).not.toBeInTheDocument());
  });
});
```

Escape closes through Mantine's `onClose`, which clears the stack when no form is dirty.
If the title text differs from "Notes", use the label `getSidebarInfo` gives `['notes']`.

Run all of these. Expected: the rewritten tests FAIL (`useOnViewEdit` and `buildUseCreate`
still dispatch to Redux; `VariablesSidebar` still relies on the reducer; the sidebar reads
the Redux stack, so the pushed form never opens).

- [ ] **Step 3: Move every writer to `useDrawer()`**

`ReactionDetailsSidebar.tsx`:

```tsx
  const reactionPathComponentsList = useDrawerStack();
  const drawer = useDrawer();
  …
  const onFormClose = useCallback(() => {
    drawer.pop();
    closeCloseConfirmation();
  }, [drawer, closeCloseConfirmation]);

  const onSidebarClose = useCallback(() => {
    drawer.clear();
    closeCloseAllConfirmation();
  }, [drawer, closeCloseAllConfirmation]);
  …
        onClick: () => {
          drawer.truncate(index);
        },
  …
  }, [drawer, reactionPathComponentsList, sidebarInfos]);
```

The unmount cleanup that calls `onSidebarClose` stays: `drawer` is stable, so the effect
runs its cleanup only on unmount. Delete `useSelector`, `useAppDispatch`, and the slice
imports.

`reactionViewDeleteButtons.utils.ts`:

```ts
export const useOnViewEdit = ({
  pathComponents,
  historyPathComponents,
}: Omit<ReactionViewDeleteButtonsProps, 'entityName'>) => {
  const drawer = useDrawer();
  return useCallback(() => {
    if (historyPathComponents) {
      drawer.set(historyPathComponents.concat([pathComponents]));
    } else {
      drawer.push(pathComponents);
    }
  }, [drawer, pathComponents, historyPathComponents]);
};
```

`ReactionValidationList.tsx` (`ErrorWarningMessageDisplay`):
`const drawer = useDrawer();` and `drawer.set(reactionFlatPathToSidebars(message.path));`.

`VariablesSidebar.tsx`:

```tsx
  const drawer = useDrawer();
  …
  const onVariableClick = (pathComponentsList: Array<ReactionPathComponents>) => {
    // Opening the variable's entity replaces this drawer with the reaction drawer.
    onClose();
    drawer.set(pathComponentsList);
  };
```

`ReactionEntityDelete.tsx`: `const drawer = useDrawer();` and
`if (shouldCloseSidebar) { drawer.pop(); }`; add `drawer` to the callback's dependencies.

`buildUseCreate.ts`, `InputsComponentList.tsx`, `ProductComponentsList.tsx`:
`const drawer = useDrawer();` and `drawer.push(<path>)` in place of
`dispatch(addReactionPathComponentToList(<path>))`; add `drawer` to dependencies.
`WorkupInput.tsx`: the two pushes become `drawer.push(currentPath); drawer.push(currentPath.concat([COMPONENTS_FIELD, index]));`.

`OpenSingleEntityButton.tsx`: `const drawer = useDrawer();` and
`const onOpen = useCallback(() => drawer.push(pathComponents), [drawer, pathComponents]);`;
delete `useAppDispatch`.

`Identifiers.tsx`, `Observation.tsx`, `Workups.tsx`: `drawer.set([newIdentifierPath])`
in place of `dispatch(setReactionPathComponentsList([newIdentifierPath]))`; the field
update stays a dispatch until E.

- [ ] **Step 4: Delete the slice**

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
git rm -r store/features/reactionForm
```

In `store/features/features.reducer.ts`, delete the `reactionFormReducer` import and the
`reactionForm:` line. In `store/features/variablesSidebar/variablesSidebar.reducer.ts`,
delete the matcher and its imports:

```ts
const isVariablesSidebarOpened = createReducer(false, builder => {
  builder.addCase(setVariablesSidebarOpenedAction, (_, action) => action.payload);
});
```

(and drop `isAnyOf` from the RTK import).

```bash
grep -rn "reactionForm" ~/ord/ord-app/frontend/apps/editor/src
```

Expected: no output.

- [ ] **Step 5: Run everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: all pass, with two fewer test files (the slice's reducer and selectors tests)
and the new drawer, page, and sidebar tests.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features frontend/apps/editor/src/store/features
git status --short   # confirm the five deleted slice files are staged, and nothing else is unstaged
git commit -F "$SCRATCH/c3-msg.txt"   # "Open and close drawer forms through the provider"
```

### Task C4: Open PR C

- [ ] **Step 1: Full check and local Playwright** (as in B9). The reaction page's drawer
  test and its screenshot are the end-to-end guard.

- [ ] **Step 2: Push and open**

```bash
cd ~/ord/ord-app && git push -u origin reaction-drawer-state
gh pr create --title "Keep the reaction drawer's stack in ReactionProvider" --body-file "$SCRATCH/c-body.md"
```

Notes in the body:

- Changed assertions: `reactionViewDeleteButtons.utils.test.tsx` and
  `buildUseCreate.test.tsx` assert the resulting stack instead of the dispatched Redux
  action; `variablesSidebar.reducer.test.ts` loses its auto-close case, which
  `VariablesSidebar.test.tsx` now covers at the component.
- Behavior: a drawer open on one reaction no longer survives navigating to another
  without leaving the page (Back between two cached reactions). Before, only a
  successful crude-component search cleared it.

---

## PR D: the drawer forms read the hooks

Branch `reaction-form-hooks`, from `main` after C merges. The form builders, the eleven
custom nodes, and every form component that reads `isViewOnly`, `isTemplate`, or a slot
from `reactionContext` move to the hooks. `ReactionEntityContext` drops `reactionId`;
the template slot reads it from the provider. Edits stay dispatches until E.

Paths are relative to `frontend/apps/editor/src/`; `RE/` is
`features/reactions/ReactionEntities/` and `EFC/` is `RE/entityFormConfiguration/`.

### Task D1: The provider exposes the host's reaction ID; the builders read the hooks

**Files:**

- Modify: `features/reactions/provider/{reactionProvider.types.ts,ReactionProvider.tsx,reactionProvider.hooks.ts,reactionProvider.hooks.test.tsx}`
- Modify: `RE/reactionEntities.types.ts` (`ReactionEntityContext`), `RE/reactionEntity.context.ts`
- Modify: `RE/sidebarInfo/buildUseInitialValues.ts`, `RE/sidebarInfo/sidebarInfo.types.ts`
- Modify: `EFC/buildUseSelectItems.ts`, `EFC/reactionEntityToValidation.ts`
- Modify: `RE/ReactionEntityForm/ReactionEntityForm.tsx` (the context value and the two
  builder calls)
- Modify: `features/reactions/ReactionInteractions/ReactionValueLabel/TemplateReactionValueLabel.tsx`,
  `EFC/components/CustomIdentifiers/ComponentsLookup/ComponentsLookup.tsx` (read the ID
  from the provider)
- Modify: `test/renderInReactionView.tsx` (entity context value)
- Modify tests: `EFC/buildUseSelectItems.test.tsx`, `EFC/reactionEntityToValidation.test.tsx`,
  `EFC/buildUseCreate.test.tsx` (entity context value),
  `ReactionInteractions/ReactionValueLabel/TemplateReactionValueLabel.test.tsx`,
  `EFC/components/CustomIdentifiers/ComponentsLookup/ComponentsLookup.test.tsx` (harness)

**Interfaces:**

- Produces:
  - `ReactionProviderValue.reactionId: ReactionId` and `useReactionId(): ReactionId` — the
    ID the host gave the provider; host slots use it to reach host state.
  - `ReactionEntityContext = { pathComponents: ReactionPathComponents }`.
  - `useInitialValues(pathComponents)` (in `ReactionSidebarInfo`), `useSelectItems()`
    unchanged in shape, `useReactionEntityValidation(pathComponents, nodeEntity)`.

- [ ] **Step 1: Branch**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c reaction-form-hooks
cd frontend && npm ci
```

- [ ] **Step 2: Write the failing tests**

`reactionProvider.hooks.test.tsx`, in the static-source block:

```tsx
  it('return the host’s reaction ID', () => {
    expect(renderHook(useReactionId, { wrapper }).result.current).toBe(7);
  });
```

`buildUseSelectItems.test.tsx`: the test mocks `react-redux` and the selector and asserts
the selector's arguments. Rewrite it to assert results over a static source (the
"changed assertion" this PR lists): a wrapper of `ReactionProvider` over
`createStaticReactionSource(snapshot)` plus `reactionEntityContext.Provider value={{ pathComponents }}`,
where `snapshot.data` holds the values the old cases selected. For each old case keep
its path and expected value:

```tsx
  it('selects the entity under the context path', () => {
    const { result } = renderHook(buildUseSelectItems(['amount']), {
      wrapper: wrapperAt(['inputs', 0], { inputs: [{ amount: 'value-x' }] }),
    });
    expect(result.current).toBe('value-x');
  });
```

and likewise for the string entity path, `buildUseSelectItemsListFromMap` (sorted
values from a map, `[{ id: 'y', order: 1 }, { id: 'x', order: 2 }]`), and the stable
reference across `rerender()`. Build `wrapperAt(pathComponents, data)` in the test from
`emptyReactionData()` spread with `data`.

`reactionEntityToValidation.test.tsx`: replace its Redux `Provider` wrapper with
`ReactionProvider` over a static source whose `data.inputs` is the same
`{ in1: { id: 'in1', name: 'Existing' }, in2: { id: 'in2', name: 'Other' } }`, and call
`useReactionEntityValidation(pathComponents, entity)` (no `1`). Assertions unchanged.

`ComponentsLookup.test.tsx` and `TemplateReactionValueLabel.test.tsx`: switch
`renderWithProviders` to `renderInReactionView` (the template label with
`{ reactionId: 'template_1' }`). Assertions unchanged.

Run:

```bash
cd ~/ord/ord-app/frontend/apps/editor
npx vitest run src/features/reactions/provider src/features/reactions/ReactionEntities/entityFormConfiguration \
  src/features/reactions/ReactionInteractions/ReactionValueLabel
```

Expected: FAIL — `useReactionId` is missing; `useReactionEntityValidation` and the
select hooks still read the Redux store.

- [ ] **Step 3: `useReactionId`**

`reactionProvider.types.ts`: add `reactionId: ReactionId;` (type import from
`store/entities/reactions/reactions.types.ts`) to `ReactionProviderValue`.
`ReactionProvider.tsx`: include `reactionId` in the memoized value and its
dependencies. `reactionProvider.hooks.ts`:

```ts
/** The ID the host gave the provider, which host-supplied slots use to reach host state. */
export function useReactionId(): ReactionId {
  return useProviderValue().reactionId;
}
```

- [ ] **Step 4: The entity context and the builders**

`RE/reactionEntities.types.ts`:

```ts
export interface ReactionEntityContext {
  pathComponents: ReactionPathComponents;
}
```

`RE/reactionEntity.context.ts`: default `{ pathComponents: [] }`.

`RE/sidebarInfo/buildUseInitialValues.ts`:

```ts
  return function useInitialValues(
    pathComponents: ReactionPathComponents,
  ): [object, object, (values: object) => object] {
    const { id: _, ...reactionPart } = useReactionPart<Record<string, unknown>>(pathComponents)!;
```

(the `!` keeps today's behavior: the destructure threw on a missing part before too;
add a one-line comment saying a drawer form opens only for an existing entity).
`RE/sidebarInfo/sidebarInfo.types.ts`: `useInitialValues: (pathComponents: ReactionPathComponents) => …`;
drop the `ReactionId` import.

`EFC/buildUseSelectItems.ts`:

```ts
export const buildUseSelectItems = (entityPath: ReactionPathComponents | string) =>
  function useSelectItems() {
    const { pathComponents } = useContext(reactionEntityContext);
    const entityPathComponents: ReactionPathComponents =
      typeof entityPath === 'string' ? [entityPath] : entityPath;
    return useReactionPart(pathComponents.concat(entityPathComponents));
  };

export const buildUseSelectItemsListFromMap = <T>(
  entityName: string,
  compareFn: (a: T, b: T) => number,
) =>
  function useSelectItems() {
    const { pathComponents } = useContext(reactionEntityContext);
    const map = useReactionPart<Record<string, T>>([...pathComponents, entityName]);
    return useMemo(() => Object.values(map ?? {}).sort(compareFn), [map]);
  };
```

`map ?? {}` changes a throw into an empty list for a missing map; the old code threw on
`Object.values(null)`. Callers always render under an existing parent, so nothing
visible changes; keep it, since a template or a half-loaded reaction should not crash
the drawer.

`EFC/reactionEntityToValidation.ts`: drop `reactionId` from `createNamedEntityValidation`'s
hook, the record's function type, and `useReactionEntityValidation`; read the siblings
with `useReactionPart<Record<string, WithIdName<unknown>>>(objectsPath) ?? {}`.

`RE/ReactionEntityForm/ReactionEntityForm.tsx`: the context value becomes
`{ pathComponents: reactionPathComponents }` (dependencies `[reactionPathComponents]`);
the calls become `useReactionEntityValidation(reactionPathComponents, formEntity)` and
`sidebarInfo.useInitialValues(reactionPathComponents)`. The dispatch keeps using
`reactionId` from `reactionContext` until Task D2 and E.

`TemplateReactionValueLabel.tsx`:

```tsx
  const { pathComponents } = useContext(reactionEntityContext);
  const templateId = useReactionId() as string;
```

(the template slot only renders under a template provider, whose ID is a string).
`ComponentsLookup.tsx`: `const reactionId = useReactionId();` and `pathComponents` from
the entity context (E replaces the dispatch).

`test/renderInReactionView.tsx`: `value={{ pathComponents }}`. `buildUseCreate.test.tsx`:
the entity context value loses `reactionId`.

- [ ] **Step 5: Run the tests and the type check**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: PASS. `tsc -b` lists every remaining reader of `reactionEntityContext.reactionId`;
there should be none.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features frontend/apps/editor/src/test/renderInReactionView.tsx
git commit -F "$SCRATCH/d1-msg.txt"   # "Read the drawer forms' values through the provider"
```

### Task D2: The custom nodes and form components read the hooks

**Files:**

- Modify (data reads): `EFC/components/ComponentPreview/ComponentPreview.tsx`,
  `EFC/measurements/MeasurementsBasedOn.tsx`, `EFC/measurements/AuthenticStandard/AuthenticStandard.tsx`,
  `EFC/workups/WorkupInput.tsx`
- Modify (`isViewOnly`): `RE/ReactionEntityForm/ReactionEntityForm.tsx`,
  `RE/reactionEntityNode/{ReactionEntityValue,ReactionEntitySelect/ReacitonEntitySelect,ReactionEntityVPU,ReactionEntityDate,ReactionEntityDateTime,ReactionEntityData,ReactionEntityList}/*.tsx`,
  `EFC/outcomes/ProductComponentsList.tsx`, `EFC/components/CustomIdentifiers/CustomIdentifiers.tsx`,
  `EFC/provenance/UpdatePersonInfo.tsx`, `EFC/measurements/MeasurementMasses.tsx`,
  `EFC/measurements/MeasurementValueControl/MeasurementValueControl.tsx`,
  `EFC/inputs/InputsComponentsList/InputsComponentList.tsx`
- Modify (slots): `EFC/EntityListItem/EntityListItem.tsx`,
  `EFC/components/CustomIdentifiers/MolblockIdentifier/MolblockIdentifier.tsx`,
  `features/reactions/ReactionValueLabelWrapper.tsx`
- Modify tests (harness only): `EFC/components/ComponentPreview/ComponentPreview.test.tsx`
  keeps `renderInReactionView`; `EFC/measurements/AuthenticStandard/AuthenticStandard.test.tsx`
  moves from `renderWithProviders` to `renderInReactionView`

**Interfaces:**

- Consumes: `useReactionPart`, `usePreviews`, `useIsViewOnly`, `useIsTemplate`,
  `useReactionSlots`, `useReactionId` (A, B2, D1).

- [ ] **Step 1: Pin the read-only behavior that this task must keep**

These tests exist and drive `isViewOnly` through the harness, which now derives it from
the absence of actions: `MeasurementMasses.test.tsx`, `MeasurementValueControl.test.tsx`,
`MeasurementsBasedOn.test.tsx`, `ProductComponentsList.test.tsx`,
`UpdatePersonInfo.test.tsx`, `ReactionEntityList.test.tsx`, `ReactionEntityValue.test.tsx`,
`ReacitonEntitySelect.test.tsx`, `ReactionEntityVPU.test.tsx`, `ReactionEntityDate.test.tsx`,
`ReactionEntityDateTime.test.tsx`. Add one for the template label switch, in
`features/reactions/ReactionValueLabelWrapper.test.tsx`:

```tsx
const Label = ({ name }: Readonly<ReactionValueLabelProps>) => <span>value {name}</span>;
const ViewOnly = ({ name }: Readonly<ReactionValueLabelProps>) => <span>fixed {name}</span>;

it('shows the view-only label on a template field that cannot be a variable', () => {
  const { getByText } = renderInReactionView(
    <ReactionValueLabelWrapper name="mass" type={VariableType.Number} wrapperConfig={{ cannotBeVariable: true }} />,
    { reactionId: 'template_1', slots: { ValueLabel: Label, ViewOnlyLabel: ViewOnly } },
  );
  expect(getByText('fixed mass')).toBeInTheDocument();
});

it('shows the value label otherwise', () => {
  const { getByText } = renderInReactionView(
    <ReactionValueLabelWrapper name="mass" type={VariableType.Number} wrapperConfig={{ cannotBeVariable: true }} />,
    { slots: { ValueLabel: Label, ViewOnlyLabel: ViewOnly } },
  );
  expect(getByText('value mass')).toBeInTheDocument();
});
```

Read `ReactionValueLabelProps` and `VariableType` first and use a real member and the
real `wrapperConfig` shape. Run the listed tests and the new ones. Expected: PASS (they
pin today's behavior).

- [ ] **Step 2: Replace the reads**

The patterns, applied to each file in the list:

- `const { isViewOnly } = useContext(reactionContext);` → `const isViewOnly = useIsViewOnly();`
  (in `ReactionEntityDateTime.tsx`, both components).
- `const { ViewDeleteButtonsComponent } = useContext(reactionContext);` →
  `const { ViewDeleteButtons } = useReactionSlots();` and rename the JSX element.
  `MeasurementValueControl.tsx`: `const isViewOnly = useIsViewOnly(); const { ValueLabel } = useReactionSlots();`.
- A destructure of `reactionId` together with those fields (`ProductComponentsList`,
  `CustomIdentifiers`, `InputsComponentList`, `AuthenticStandard`, `WorkupInput`,
  `MeasurementsBasedOn`) keeps `reactionId` only where a dispatch still uses it, read as
  `const reactionId = useReactionId();`.
- `ReactionEntityForm.tsx`: `const isViewOnly = useIsViewOnly(); const isTemplate = useIsTemplate(); const reactionId = useReactionId();`.
- `ReactionValueLabelWrapper.tsx`:

  ```tsx
  const isTemplate = useIsTemplate();
  const { ValueLabel, ViewOnlyLabel } = useReactionSlots();
  return isTemplate && wrapperConfig?.cannotBeVariable ? (
    <ViewOnlyLabel name={name} wrapperConfig={wrapperConfig} type={type} />
  ) : (
    <ValueLabel name={name} type={type} wrapperConfig={wrapperConfig} />
  );
  ```

Data reads:

- `ComponentPreview.tsx`:

  ```tsx
  const { pathComponents } = useContext(reactionEntityContext);
  const component = useReactionPart<ReactionInputComponent>(pathComponents)!;
  const previewStates = usePreviews([component.id]);
  ```

  (`component.id` threw on a missing part before; the `!` keeps that.)
- `MeasurementsBasedOn.tsx`:
  `const analyses = useReactionPart<ReactionOutcome['analyses']>(analysesPath) ?? {};`
- `AuthenticStandard.tsx`:
  `const authenticStandard = useReactionPart<ReactionInputComponent>(currentPath);`
  (`!!authenticStandard` already guards null).
- `WorkupInput.tsx`: `const input = useReactionPart<ReactionInputWithoutName>(currentPath);`

Delete `reactionContext` imports, `useSelector`, and `selectReactionPartByPath` /
`selectPreviewsByIdsWrapper` imports where they become unused.

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
grep -rln "reactionContext" features/reactions/ReactionEntities features/reactions/ReactionValueLabelWrapper.tsx
grep -rln "selectReactionPartByPath\|selectPreviewsByIdsWrapper" features
```

Expected: the first grep lists only files whose remaining read is a dispatch's
`reactionId` (none, if every one now uses `useReactionId`); the second prints nothing.

- [ ] **Step 3: Run everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features
git commit -F "$SCRATCH/d2-msg.txt"   # "Read drawer form state and slots through the provider"
```

### Task D3: The contract suite covers the drawer forms

**Files:**

- Modify: `store/entities/reactions/reactionSourceContract.test.tsx` (or
  `test/renderOverBothSources.tsx` if B7 moved the helper there)

**Interfaces:**

- Consumes: `renderOverBothSources`, `fullReactionSnapshot` (B7).

- [ ] **Step 1: Write the test**

Render a drawer form for each entity the fixture holds, over both sources, and compare.
A form needs the node registry and its sidebar info:

```tsx
function FormAt({ pathComponents }: Readonly<{ pathComponents: ReactionPathComponents }>) {
  return (
    <nodeToComponentContext.Provider value={reactionNodeToComponent}>
      <ReactionEntityForm
        reactionPathComponents={pathComponents}
        sidebarInfo={getSidebarInfo([...pathComponents].reverse())}
        isHidden={false}
        onFormClose={() => undefined}
        onSetFormDirty={() => undefined}
      />
    </nodeToComponentContext.Provider>
  );
}

const firstInputId = Object.keys(fullReactionSnapshot().data.inputs)[0];
const FORMS: Array<ReactionPathComponents> = [
  ['inputs', firstInputId],
  ['inputs', firstInputId, 'components', 0],
  ['outcomes', 0],
  ['outcomes', 0, 'products', 0],
  ['conditions'],
  ['setup'],
  ['notes'],
  ['provenance'],
  ['identifiers', 0],
  ['observations', 0],
  ['workups', 0],
];

describe('the drawer forms over either source', () => {
  it.each(FORMS)('render %j the same', (...pathComponents) => {
    const [overStatic, overRedux] = renderOverBothSources(
      <FormAt pathComponents={pathComponents} />,
    );
    expect(overStatic).toBe(overRedux);
  });
});
```

`it.each` spreads an array row into arguments, so the row is reassembled with
`...pathComponents`. Drop a path from `FORMS` only if the fixture has no such entity
(check `test/fullReaction.ts`), and say which in the commit message.

The form's `useForm` builds a random `formKey` with `crypto.randomUUID()`; if it reaches
the HTML, extend `normalizeIds` to replace UUIDs too.

- [ ] **Step 2: Run it**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/store/entities/reactions/reactionSourceContract.test.tsx
```

Expected: PASS. A difference means a form component still reads the store; fix the
component.

- [ ] **Step 3: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/store/entities/reactions/reactionSourceContract.test.tsx
git commit -F "$SCRATCH/d3-msg.txt"   # "Check the drawer forms render the same over both sources"
```

### Task D4: Open PR D

Full check and local Playwright as in B9, then:

```bash
cd ~/ord/ord-app && git push -u origin reaction-form-hooks
gh pr create --title "Read the drawer forms through ReactionProvider" --body-file "$SCRATCH/d-body.md"
```

Notes in the body:

- Changed assertions: `buildUseSelectItems.test.tsx` asserted the selector's arguments;
  it now asserts the selected values over a static source, for the same paths.
  `reactionEntityToValidation.test.tsx` calls the hook without a reaction ID.
- `buildUseSelectItemsListFromMap` returns an empty list for a missing map instead of
  throwing.

---

## PR E: edits go through `useReactionActions()`

Branch `reaction-actions`, from `main` after D merges. Every edit in the view and the
drawer calls the provider's actions; the compound lookup's flags become local state;
"Use my info" asks the actions for the current person; the drawer title's Delete icon
shows only when the reaction can be edited; and `reactionContext`, which no component
reads any more, is deleted.

Paths are relative to `frontend/apps/editor/src/`; `RE/` and `EFC/` as in D.

### Task E1: The actions add a compound by name and know the current person

**Files:**

- Modify: `features/reactions/provider/reactionProvider.types.ts`
- Modify: `store/entities/reactions/reduxReactionSource.ts`, `reduxReactionSource.test.tsx`
- Modify: `pages/ReactionPage/useDatasetReactionProviderProps.ts`, `test/renderInReactionView.tsx`
- Modify: `features/reactions/provider/reactionProvider.hooks.test.tsx` (the two actions literals)

**Interfaces:**

- Produces, in `reactionProvider.types.ts`:

  ```ts
  export interface ReactionActions {
    update(pathComponents: ReactionPathComponents, newValue: unknown): Promise<void>;
    remove(pathComponents: ReactionPathComponents): Promise<void>;
    /**
     * Resolves a compound name to a structure and appends it as a SMILES identifier to the
     * list at `identifiersPath`. Resolves true once the identifier is added (its save
     * reports its own failure) and false when the name does not resolve.
     */
    addIdentifierByName(identifiersPath: ReactionPathComponents, name: string): Promise<boolean>;
    /** The signed-in person, for filling provenance; absent when the host has none. */
    currentPerson?(): ReactionPerson | undefined;
  }
  ```

  (`ReactionPerson` is a type import from
  `store/entities/reactions/reactionProvenance/reactionProvenance.types.ts`.)
- Produces, in `reduxReactionSource.ts`:

  ```ts
  /** What the actions need from the editor's store. */
  export interface ReduxReactionStore {
    dispatch: ThunkDispatch<AppState, never, Action>;
    getState: () => AppState;
  }
  export function reduxReactionActions(store: ReduxReactionStore, reactionId: ReactionId): ReactionActions;
  ```

- [ ] **Step 1: Branch**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c reaction-actions
cd frontend && npm ci
```

- [ ] **Step 2: Write the failing tests**

In `reduxReactionSource.test.tsx`, change the three `reduxReactionActions(store.dispatch, 1)`
calls (and the hand-built `dispatch` one) to `reduxReactionActions(store, 1)` /
`reduxReactionActions({ dispatch, getState: store.getState }, 1)`, and add the cases
ported from `store/entities/reactions/reactionsInputs/reactionInputs.thunks.test.ts`
and `UpdatePersonInfo.test.tsx`:

```tsx
describe('reduxReactionActions.addIdentifierByName', () => {
  const path = ['inputs', 'in1', 'components', 0, 'identifiers'];

  it('resolves the name and appends a SMILES identifier', async () => {
    const recorded: Array<UnknownAction> = [];
    const store = makeStore(recorded);
    axiosMock.post.mockResolvedValue({ data: { smiles: 'O' } });
    axiosMock.patch.mockResolvedValue({ data: {} });
    await expect(reduxReactionActions(store, 1).addIdentifierByName(path, 'water')).resolves.toBe(true);
    expect(axiosMock.post).toHaveBeenCalledWith('/resolve-compound', {
      identifier_type: 'name',
      identifier: 'water',
    });
    const request = recorded.find(addUpdateReactionFieldActions.request.match);
    expect(request?.payload.pathComponents).toEqual([...path, 0]);
    expect(request?.payload.newValue).toMatchObject({ value: 'O', details: 'water' });
  });

  it('resolves false and changes nothing when the name does not resolve', async () => {
    const recorded: Array<UnknownAction> = [];
    const store = makeStore(recorded);
    axiosMock.post.mockRejectedValue(new Error('not found'));
    await expect(reduxReactionActions(store, 1).addIdentifierByName(path, 'unobtainium')).resolves.toBe(false);
    expect(recorded.some(addUpdateReactionFieldActions.request.match)).toBe(false);
  });
});

describe('reduxReactionActions.currentPerson', () => {
  it('maps the signed-in user to a provenance person, skipping empty fields', () => {
    const store = makeStore(undefined, {
      name: 'Me',
      email: 'me@example.com',
      orcid_id: '0000-0001',
      organization: '',
    });
    expect(reduxReactionActions(store, 1).currentPerson?.()).toEqual({
      name: 'Me',
      email: 'me@example.com',
      orcid: '0000-0001',
    });
  });

  it('returns undefined before the user loads', () => {
    expect(reduxReactionActions(makeStore(), 1).currentPerson?.()).toBeUndefined();
  });
});
```

`makeStore` gains an optional second argument, `self?: Partial<User>`, which it puts
at `entities.users.self` in the preloaded state (read `store/entities/users/users.types.ts`
for the field names, and use one that exists in place of `organization` if it does
not). Give `makeStore`'s reaction 1 an input `in1` with one component, so `path` exists.

Every `ReactionActions` literal in a test gains `addIdentifierByName: vi.fn()`: the two
in `reactionProvider.hooks.test.tsx` and the one in `buildUseCreate.test.tsx`'s wrapper
(C3). `tsc -b` lists any other.

Run:

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/store/entities/reactions/reduxReactionSource.test.tsx
```

Expected: FAIL — `addIdentifierByName` and `currentPerson` do not exist; the signature
takes a dispatch.

- [ ] **Step 3: Implement**

`reduxReactionSource.ts`:

```ts
const PERSON_FIELDS: Array<[keyof ReactionPerson, keyof User]> = [
  ['name', 'name'],
  ['email', 'email'],
  ['orcid', 'orcid_id'],
];

function personFromUser(user: User): ReactionPerson {
  return PERSON_FIELDS.reduce((person: ReactionPerson, [personKey, userKey]) => {
    const value = user[userKey];
    return value ? { ...person, [personKey]: value } : person;
  }, {});
}

function smilesIdentifier(name: string, smiles: string): ReactionCompoundIdentifier {
  return ordCompoundIdentifierToReaction(
    create(CompoundIdentifierSchema, {
      type: CompoundIdentifier_CompoundIdentifierType.SMILES,
      value: smiles,
      details: name,
    }),
  );
}

/**
 * Edits one reaction through the thunks that apply a change optimistically and save it.
 * (keep the rest of today's doc comment)
 */
export function reduxReactionActions(
  { dispatch, getState }: ReduxReactionStore,
  reactionId: ReactionId,
): ReactionActions {
  return {
    update: async (pathComponents, newValue) => {
      await dispatch(addUpdateReactionField({ reactionId, pathComponents, newValue }));
    },
    remove: async pathComponents => {
      await dispatch(deleteReactionField({ reactionId, pathComponents }));
    },
    addIdentifierByName: async (identifiersPath, name) => {
      let smiles: string;
      try {
        const response = await axiosInstance.post<{ smiles: string }>('/resolve-compound', {
          identifier_type: 'name',
          identifier: name,
        });
        smiles = response.data.smiles;
      } catch (_e) {
        return false;
      }
      // Read the list after the request returns, so the new identifier goes last.
      const identifiers = (selectReactionPartByPath(reactionId, identifiersPath)(getState()) ??
        []) as Array<ReactionCompoundIdentifier>;
      // The edit applies at once; its save settles later and reports its own failure.
      void dispatch(
        addUpdateReactionField({
          reactionId,
          pathComponents: [...identifiersPath, identifiers.length],
          newValue: smilesIdentifier(name, smiles),
        }),
      );
      return true;
    },
    currentPerson: () => {
      const user = selectSelf(getState());
      return user ? personFromUser(user) : undefined;
    },
  };
}
```

Copy the imports from `reactionInputs.thunks.ts` (`create`, `CompoundIdentifierSchema`,
`CompoundIdentifier_CompoundIdentifierType`, `ordCompoundIdentifierToReaction`,
`ReactionCompoundIdentifier`) and `UpdatePersonInfo.tsx` (`User`, `selectSelf`).

`useDatasetReactionProviderProps.ts`:

```ts
  const store = useStore<AppState>();
  const dispatch = useAppDispatch();
  const source = useReduxReactionSource(reactionId);
  const actions = useMemo(
    () =>
      canEdit
        ? reduxReactionActions({ dispatch, getState: store.getState }, reactionId)
        : undefined,
    [canEdit, dispatch, store, reactionId],
  );
```

`test/renderInReactionView.tsx`: `reduxReactionActions(store, reactionId)`.

- [ ] **Step 4: Run the tests**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider \
  frontend/apps/editor/src/store/entities/reactions/reduxReactionSource.ts \
  frontend/apps/editor/src/store/entities/reactions/reduxReactionSource.test.tsx \
  frontend/apps/editor/src/pages/ReactionPage/useDatasetReactionProviderProps.ts \
  frontend/apps/editor/src/test/renderInReactionView.tsx
git commit -F "$SCRATCH/e1-msg.txt"   # "Add the compound lookup and the current person to the reaction actions"
```

### Task E2: Every edit calls the actions

**Files:**

- Modify: `RE/ReactionEntityForm/ReactionEntityForm.tsx`, `EFC/buildUseCreate.ts`,
  `EFC/outcomes/ProductComponentsList.tsx`, `EFC/inputs/InputsComponentsList/InputsComponentList.tsx`,
  `EFC/components/CustomIdentifiers/CustomIdentifiers.tsx`,
  `EFC/measurements/AuthenticStandard/AuthenticStandard.tsx`, `EFC/workups/WorkupInput.tsx`,
  `features/reactions/ReactionView/{Identifiers,Observation,Workups}/*.tsx`,
  `RE/ReactionEntityDelete/ReactionEntityDelete.tsx`
- Modify test: `EFC/buildUseCreate.test.tsx` (its wrapper's actions)

**Interfaces:**

- Consumes: `useReactionActions()` (A), `ReactionActions.update/remove` (A).

The harness gives editable reactions the real `reduxReactionActions`, which dispatch the
same thunks the components dispatched, so the tests that mock `addUpdateReactionField`
(`ReactionEntityForm.paste.test.tsx`, `ReactionEntityForm.saveAndClose.test.tsx`) keep
their assertions unchanged.

- [ ] **Step 1: Point `buildUseCreate.test.tsx` at real actions over its dispatch spy**

In the wrapper C built, replace `actions = { update: vi.fn(), … }` with
`reduxReactionActions({ dispatch, getState: () => ({}) as AppState }, 7)`, where
`dispatch` is the hoisted spy `useAppDispatch` returns. The assertions on
`dispatch(addUpdateReactionField(…))` then hold unchanged once `useCreate` edits through
the actions. Run it: `npx vitest run src/features/reactions/ReactionEntities/entityFormConfiguration/buildUseCreate.test.tsx`.
Expected: PASS (today's code dispatches directly; after Step 2 it dispatches through the
actions, and the test must still pass).

- [ ] **Step 2: Replace the dispatches**

The pattern, in each file:

```tsx
  const actions = useReactionActions();
  …
  void actions?.update(pathComponents, newValue);
```

in place of `dispatch(addUpdateReactionField({ reactionId, pathComponents, newValue }))`,
keeping each call's position (an edit before a drawer push stays before it). Replace
`dispatch`/`reactionId` in each callback's dependency list with `actions`. Specifics:

- `ReactionEntityForm.tsx` `onSubmit`: `if (!actions) return;` replaces
  `if (isViewOnly) return;` and its comment becomes "A form is submitted only for an
  editable reaction, even if some field stayed editable."; then
  `void actions.update(reactionPathComponents, values);`.
- `AuthenticStandard.tsx` and `WorkupInput.tsx`: `onRemove` is
  `void actions?.update(currentPath, null);` (a removal here is an update to null, as
  today).
- `ReactionEntityDelete.tsx`:

  ```tsx
    const handleRemove = useCallback(() => {
      if (shouldCloseSidebar) {
        drawer.pop();
      }
      if (onRemove) {
        onRemove();
      } else {
        void actions?.remove(pathComponents);
      }
      closeConfirmation();
    }, [actions, closeConfirmation, drawer, onRemove, pathComponents, shouldCloseSidebar]);
  ```

  Its `reactionId` prop stays until E4.
- `Identifiers.tsx`, `Observation.tsx`, `Workups.tsx`: delete the `reactionContext` read
  and `useAppDispatch`.

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
grep -rn "addUpdateReactionField\|deleteReactionField\|useAppDispatch" features/reactions/ReactionView features/reactions/ReactionEntities
```

Expected: only `ComponentsLookup.tsx` (E3) and `CustomIdentifiers.tsx`'s lookup flags (E3)
remain.

- [ ] **Step 3: Run everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: PASS with no assertion edits.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features
git commit -F "$SCRATCH/e2-msg.txt"   # "Edit reactions through the provider's actions"
```

### Task E3: The lookup's flags are local state; "Use my info" asks the actions

**Files:**

- Modify: `EFC/components/CustomIdentifiers/CustomIdentifiers.tsx`,
  `EFC/components/CustomIdentifiers/ComponentsLookup/ComponentsLookup.tsx`,
  `EFC/provenance/UpdatePersonInfo.tsx`
- Modify: `store/features/features.reducer.ts`
- Delete: `store/features/reactionLookup/` (actions, reducer, selectors, and their two
  tests), `store/entities/reactions/reactionsInputs/reactionInputs.thunks.ts`,
  `reactionInputs.thunks.test.ts`, `reactionInputs.actions.ts`
- Modify test: `ComponentsLookup.test.tsx`
- Create test: `EFC/components/CustomIdentifiers/CustomIdentifiers.test.tsx`

**Interfaces:**

- Consumes: `ReactionActions.addIdentifierByName`, `ReactionActions.currentPerson` (E1).
- Produces: `ComponentsLookup({ onClose })` unchanged in props.

- [ ] **Step 1: Write the failing tests**

`ComponentsLookup.test.tsx`, beside its smoke test:

```tsx
vi.mock('store/axiosInstance.ts', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('common/utils/showNotification.tsx', () => ({ showNotification: vi.fn() }));

const componentPath = ['inputs', 'in1', 'components', 0];
const reaction = {
  ...emptyReactionData(),
  inputs: { in1: { id: 'in1', name: 'in1', components: [{ id: 'c1', identifiers: [] }] } },
} as unknown as AppReaction;

it('adds the resolved compound and closes', async () => {
  axiosMock.post.mockResolvedValue({ data: { smiles: 'O' } });
  axiosMock.patch.mockResolvedValue({ data: {} });
  const onClose = vi.fn();
  const { getByLabelText, getByRole, store } = renderInReactionView(
    <ComponentsLookup onClose={onClose} />,
    { reaction, pathComponents: componentPath },
  );
  fireEvent.change(getByLabelText('Compound name'), { target: { value: 'water' } });
  fireEvent.click(getByRole('button', { name: /search|look up/i }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  const component = store.getState().entities.reactions.reactionsById[1].data.inputs.in1.components[0];
  expect(component.identifiers.at(-1)).toMatchObject({ value: 'O', details: 'water' });
});

it('says so when the name does not resolve, and stays open', async () => {
  axiosMock.post.mockRejectedValue(new Error('not found'));
  const onClose = vi.fn();
  const { getByLabelText, getByRole, findByText } = renderInReactionView(
    <ComponentsLookup onClose={onClose} />,
    { reaction, pathComponents: componentPath },
  );
  fireEvent.change(getByLabelText('Compound name'), { target: { value: 'unobtainium' } });
  fireEvent.click(getByRole('button', { name: /search|look up/i }));
  expect(await findByText('Compound not found')).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
});
```

Read the submit button's text in `ComponentsLookup.tsx` and use it exactly instead of the
regular expression; declare `axiosMock` as `reduxReactionSource.test.tsx` does.

`CustomIdentifiers.test.tsx` (new; none existed): with an editable reaction at a
component path, clicking the "Via Look up Name" option of "Add Identifier" opens the
lookup (its "Compound name" field shows), and its close control removes it. Use the
exact button texts from `CustomIdentifiers.tsx`.

`UpdatePersonInfo.test.tsx` needs no change: it mocks `selectSelf`, which the harness's
`reduxReactionActions.currentPerson` now reads.

Run the three tests. Expected: FAIL — the lookup still dispatches the thunk the store
answers through `features.reactionLookup`, which the new tests do not observe in the
same way; in particular `onClose` is never called, because closing went through the
slice.

- [ ] **Step 2: Local state**

`CustomIdentifiers.tsx`:

```tsx
  const [isLookupOpened, { open: openLookup, close: closeLookup }] = useDisclosure();
```

in place of `selectIsReactionLookupOpen` and the two dispatching callbacks; render
`{isLookupOpened && <ComponentsLookup onClose={closeLookup} />}`, and pass `openLookup`
where `openAddCustomIdentifier` was used.

`ComponentsLookup.tsx`:

```tsx
export function ComponentsLookup({ onClose }: Readonly<ComponentsLookupProps>) {
  const { pathComponents } = useContext(reactionEntityContext);
  const actions = useReactionActions();
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  …form as before…
  useEffect(() => {
    if (hasError) {
      setFieldError('search', 'Compound not found');
    }
  }, [hasError, setFieldError]);

  useEffect(() => {
    if (hasError && values.search.length > 0) {
      setHasError(false);
    }
  }, [hasError, values.search]);

  const lookUp = async (name: string) => {
    if (!actions) {
      return;
    }
    setIsLoading(true);
    const found = await actions.addIdentifierByName(pathComponents.concat('identifiers'), name);
    setIsLoading(false);
    if (found) {
      onClose();
    } else {
      setHasError(true);
    }
  };

  const onSubmit = (values: { search: string }, event?: FormEvent<HTMLFormElement>) => {
    // The lookup sits inside the drawer's form; keep its submit from reaching that form.
    event?.stopPropagation();
    void lookUp(values.search);
  };
```

`isLoading` and `hasError` keep today's meaning: loading spans the request only, the
error shows until the field changes.

`UpdatePersonInfo.tsx`:

```tsx
export function UpdatePersonInfo({ name, formMethods: { setValues }, text }: …) {
  const currentPerson = useReactionActions()?.currentPerson;

  const updateFields = useCallback(() => {
    const person = currentPerson?.();
    if (!person) {
      return;
    }
    const pathComponents: ReactionPathComponents = name.split('.');
    setValues(prevValues =>
      deepMergeWithArrayMerge(prevValues, generateDeepPartialReactionByPath(pathComponents, person)),
    );
  }, [currentPerson, name, setValues]);

  return currentPerson ? <Button onClick={updateFields}>{text}</Button> : null;
}
```

(no actions means read-only, which hid the button before too). Delete the user-field
map, `selectSelf`, `User`, and `reactionContext` imports.

- [ ] **Step 3: Delete the slice and the thunk**

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
git rm -r store/features/reactionLookup
git rm store/entities/reactions/reactionsInputs/reactionInputs.thunks.ts \
  store/entities/reactions/reactionsInputs/reactionInputs.thunks.test.ts \
  store/entities/reactions/reactionsInputs/reactionInputs.actions.ts
```

Delete the `reactionLookupReducer` import and the `reactionLookup:` line in
`store/features/features.reducer.ts`.

```bash
grep -rn "reactionLookup\|addIdentifierByNameActions\|reactionInputs.thunks" ~/ord/ord-app/frontend/apps/editor/src
```

Expected: no output.

- [ ] **Step 4: Run everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features frontend/apps/editor/src/store
git status --short   # the deleted files are staged; nothing else unstaged
git commit -F "$SCRATCH/e3-msg.txt"   # "Keep the compound lookup's state in its components"
```

### Task E4: No Delete icon on a read-only drawer

**Files:**

- Modify: `RE/ReactionEntityTitle/ReactionEntityTitle.tsx`, `reactionEntityTitle.types.ts`,
  `RE/ReactionEntityDelete/ReactionEntityDelete.tsx` (drop `reactionId`),
  `features/reactions/ReactionInteractions/ReactionViewDeleteButtons/ReactionEditDeleteButtons.tsx`,
  `features/reactions/ReactionDetailsSidebar/ReactionDetailsSidebar.tsx` (drop `reactionId`),
  `pages/ReactionPage/ReactionPage.tsx`, `pages/TemplatePage/TemplatePage.tsx`
- Modify tests: `ReactionEntityTitle.test.tsx`, `reactionEntityTitle.utils.test.tsx`,
  `ReactionDetailsSidebar.test.tsx`, `pages/ReactionPage/ReactionPage.test.tsx` and
  `pages/TemplatePage/TemplatePage.test.tsx` if they pass `reactionId` to the sidebar
- Modify: `store/entities/reactions/reactionSourceContract.test.tsx` (read-only contract)

**Interfaces:**

- Produces: `ReactionEntityTitleProps = { pathComponents }`;
  `ReactionEntityDelete({ entityName, pathComponents, shouldCloseSidebar?, onRemove? })`;
  `ReactionDetailsSidebar()` takes no props.

- [ ] **Step 1: Write the failing tests**

`ReactionEntityTitle.test.tsx`:

```tsx
describe('ReactionEntityTitle', () => {
  const title = (options: Parameters<typeof renderInReactionView>[1]) =>
    renderInReactionView(
      <ReactionEntityTitle
        pathComponents={['notes']}
        entityName="Notes"
        hasDelete
      />,
      options,
    );

  it('offers Delete when the reaction can be edited', () => {
    expect(title({}).getByRole('button', { name: /remove|delete/i })).toBeInTheDocument();
  });

  it.each([
    ['a read-only dataset', { isViewOnly: true }],
    ['a template', { reactionId: 'template_1' }],
  ] as const)('offers no Delete on %s', (_name, options) => {
    expect(title(options).queryByRole('button', { name: /remove|delete/i })).not.toBeInTheDocument();
  });
});
```

`ReactionEntityDelete`'s `ActionIcon` has no accessible name today; give it
`aria-label={`Remove ${entityName}`}` (matching its popover title) and query
`{ name: 'Remove Notes' }` instead of the regular expression. Keep the existing smoke
case.

In the contract test, add the read-only check the design asks for: over a static source
with no actions, a drawer form shows no edit control.

```tsx
function ReadOnlyWrapper({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <Provider store={makeStore(false)}>
      <MantineProvider>
        <ReactionProvider
          reactionId={1}
          source={createStaticReactionSource(fullReactionSnapshot())}
          slots={slots}
        >
          {children}
        </ReactionProvider>
      </MantineProvider>
    </Provider>
  );
}

describe('a read-only drawer', () => {
  it.each(FORMS)('shows no edit control in %j', (...pathComponents) => {
    const { queryAllByRole } = render(<FormAt pathComponents={pathComponents} />, {
      wrapper: ReadOnlyWrapper,
    });
    const labels = queryAllByRole('button').map(button => button.textContent?.trim() ?? button.getAttribute('aria-label'));
    for (const forbidden of ['Save', 'Save and Close', 'Paste', 'Add', 'Use my info', 'Edit']) {
      expect(labels).not.toContain(forbidden);
    }
    expect(queryAllByRole('button', { name: /^Remove / })).toHaveLength(0);
  });
});
```

Render the `ReactionEntityTitle` the drawer uses for each form too (its `sidebarTitle`
from `getSidebarInfo`), since that is where the Delete icon lives. Read the forms for
the exact labels of their add buttons ("Add component", "Product", "Identifier", …) and
list them all in `forbidden`.

Run them. Expected: FAIL — the editable case finds no named button; the read-only cases
find the icon.

- [ ] **Step 2: Gate the icon and drop the ID plumbing**

`ReactionEntityTitle.tsx`:

```tsx
export function ReactionEntityTitle({
  pathComponents,
  entityName,
  hasDelete,
  description,
}: Readonly<ReactionEntityTitleProps & ReactionEntityTitleConstructorProps>) {
  const isViewOnly = useIsViewOnly();
  …
        {hasDelete && !isViewOnly && (
          <ReactionEntityDelete
            entityName={entityName}
            pathComponents={pathComponents}
            shouldCloseSidebar
          />
        )}
```

`reactionEntityTitle.types.ts`: `ReactionEntityTitleProps = { pathComponents: ReactionPathComponents }`.
`ReactionEntityDelete.tsx`: drop the `reactionId` prop and add the `aria-label`.
`ReactionEditDeleteButtons.tsx`: drop its `reactionContext` read and stop passing
`reactionId`. `ReactionDetailsSidebar.tsx`: drop its props; render
`<SidebarTitle pathComponents={…} />`. The pages render `<ReactionDetailsSidebar />`.

`reactionEntityTitle.utils.test.tsx` asserts that the factory forwards `reactionId`;
render `<Title pathComponents={['inputs', 0]} />` and expect `'Input:true:inputs.0'`
(update its echo mock to drop `reactionId`). This is a changed assertion; it follows the
prop's removal.

- [ ] **Step 3: Run everything**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src
git commit -F "$SCRATCH/e4-msg.txt"   # "Show the drawer's Delete icon only on an editable reaction"
```

### Task E5: Playwright: a read-only dataset shows no edit controls

**Files:**

- Modify: `frontend/apps/editor/e2e/seed.ts`
- Create: `frontend/apps/editor/e2e/readOnlyReaction.spec.ts`

**Interfaces:**

- Produces: `seedReadOnlyReaction(request): Promise<{ datasetId: number; reactionId: number }>`
  — the fixture reaction in a dataset whose group the e2e user belongs to as a viewer.

- [ ] **Step 1: Seed a read-only dataset**

The no-auth stack has one user. A group's admin may change any member's role
(`PATCH /groups/{id}/members`, `ord_app/service_api/resources/v1/group.py`), so the seed
demotes the user in the group it just created:

```ts
async function call<T>(
  request: APIRequestContext,
  method: 'get' | 'patch',
  url: string,
  options: object = {},
): Promise<T> {
  const response = await request[method](`${API}${url}`, { headers, ...options });
  if (!response.ok()) {
    throw new Error(`${method.toUpperCase()} ${url} returned ${response.status()}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

/** Seeds the fixture reaction in a dataset the e2e user may only view. */
export async function seedReadOnlyReaction(
  request: APIRequestContext,
): Promise<{ datasetId: number; reactionId: number }> {
  const { groupId, datasetId, reactionId } = await seedReaction(request);
  const me = await call<{ id: number }>(request, 'get', '/users/me');
  await call(request, 'patch', `/groups/${groupId}/members`, {
    data: { user_id: me.id, role: 'viewer' },
  });
  return { datasetId, reactionId };
}
```

Check `GroupUpdateMemberSchema` (`ord_app/service_api/schemas/groups.py`) for the field
names before relying on them.

- [ ] **Step 2: The spec**

`e2e/readOnlyReaction.spec.ts`:

```ts
import { expect, test } from '@playwright/test';
import { seedReadOnlyReaction } from './seed.ts';

let reactionUrl: string;

test.beforeAll(async ({ request }) => {
  const { datasetId, reactionId } = await seedReadOnlyReaction(request);
  reactionUrl = `/datasets/${datasetId}/reactions/${reactionId}`;
});

test('a read-only reaction shows no edit controls, in the page or the drawer', async ({ page }) => {
  await page.goto(reactionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('acid', { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  // Edit rights are decided once the user and the dataset's groups load; wait for both.
  await expect(page.getByText('E2E User', { exact: true })).toBeVisible();
  await page.waitForLoadState('networkidle');

  for (const name of ['Edit', 'Remove', 'Input', 'Outcome']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  await page.getByRole('button', { name: 'View', exact: true }).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('button', { name: /^Remove / })).toHaveCount(0);
  for (const name of ['Save', 'Save and Close', 'Paste']) {
    await expect(drawer.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
});
```

Read the page for the exact add-button labels ("Input", "Outcome", …) with
`npx playwright test --debug` and list the ones the editable page shows.

- [ ] **Step 3: Run it locally, then commit**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx playwright test e2e/readOnlyReaction.spec.ts
```

Expected: PASS. To prove it can fail, temporarily remove `!isViewOnly &&` from
`ReactionEntityTitle.tsx` and rerun: the drawer assertion fails. Restore it.

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/e2e/seed.ts frontend/apps/editor/e2e/readOnlyReaction.spec.ts
git commit -F "$SCRATCH/e5-msg.txt"   # "Check in Playwright that a read-only reaction has no edit controls"
```

### Task E6: Retire `reactionContext`

After E4 no component reads the legacy context; the provider still supplies it.

**Files:**

- Delete: `features/reactions/reactions.context.ts`
- Modify: `features/reactions/reactions.types.ts` (delete `ReactionsContext` and its parts;
  delete the file if nothing else remains)
- Modify: `features/reactions/provider/ReactionProvider.tsx`, `reactionProvider.hooks.test.tsx`

- [ ] **Step 1: Confirm there are no readers**

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
grep -rln "reactionContext\b\|reactions.context" .
```

Expected: only `ReactionProvider.tsx` and `reactionProvider.hooks.test.tsx`. Anything
else is a reader B through E missed: move it to the hooks first.

- [ ] **Step 2: Delete it**

Remove `legacyValue` and the `reactionContext.Provider` from `ReactionProvider.tsx`, and
the sentence about it from the doc comment. In `reactionProvider.hooks.test.tsx`, delete
the assertions on the legacy context (in "are read-only without actions…" and "are
editable with actions"), keeping the `useIsViewOnly`/`useReactionActions` assertions;
rename the first case "are read-only without actions". Then `git rm` the context file
and the type.

- [ ] **Step 3: Run everything and commit**

```bash
cd ~/ord/ord-app/frontend/apps/editor && npx vitest run 2>&1 | tail -5
cd ../.. && npm run typecheck && npm run lint
cd .. && git add frontend/apps/editor/src && git commit -F "$SCRATCH/e6-msg.txt"   # "Remove the legacy reaction context"
```

### Task E7: Open PR E

Full check and local Playwright as in B9, then push and open with
`gh pr create --title "Edit reactions through the provider's actions" --body-file "$SCRATCH/e-body.md"`.

Notes in the body:

- Behavior change: the drawer title's Delete icon no longer shows on a read-only dataset
  or a template, where it removed the entity optimistically until the server refused
  and the edit rolled back.
- Changed assertions: `reactionEntityTitle.utils.test.tsx` no longer expects a
  forwarded `reactionId`; the legacy-context assertions in
  `reactionProvider.hooks.test.tsx` go with the context. The lookup slice's reducer and
  selector tests are deleted with the slice; `ComponentsLookup.test.tsx` and
  `reduxReactionSource.test.tsx` cover the same behavior.
- The lookup modal's open state is local, so it no longer reopens when another
  component's drawer mounts after the drawer was closed with the modal open.

---

## PR F: the preview renderer is a plain module in the package

Branch `preview-renderer`, from `main` after A (it touches none of B–E's files except
`staticReactionSource.ts`; run it after E to keep the order simple). The Indigo worker
moves into `packages/ui/src/reaction/previews/` behind
`renderPreviews(molblocksById, options?): Promise<PreviewsById>`, which owns one lazily
created worker, matches replies to requests by ID, and rejects when the worker fails.
The editor's middleware, the drawer's molblock preview, and the static source call it.

What exists today, and what this PR fixes along the way:

- Two Redux stores are built (`store/configureAppStore.ts` builds one at module scope for
  its `AppState` type; `core/AppRoot.tsx` builds the real one), so two preview workers
  start, and Indigo, a 12 MB build, loads three times: once in each worker and once on
  the main thread (`AppRoot` calls `initIndigo()`).
- The main thread needs Indigo only for `DisplayMolblockPreview`, which renders a
  molblock identifier synchronously and shows a broken image if Indigo has not loaded.
- If Indigo fails to load in the worker, nothing replies and the spinners never stop.

Paths in the editor are relative to `frontend/apps/editor/src/`; package paths to
`frontend/packages/ui/`.

### Task F1: `renderPreviews` and the worker, in the package

**Files:**

- Create: `src/reaction/previews/previews.types.ts`, `indigo.ts`, `indigo.test.ts`,
  `previews.worker.ts`, `previews.worker.test.ts` (copied from the editor, which keeps its
  originals until F2 so every commit builds), `renderPreviews.ts`,
  `renderPreviews.test.ts`, `index.ts`
- Modify: `package.json` (export, dependencies), `vitest.config.ts` (coverage)

**Interfaces:**

- Produces, from `@open-reaction-database/ui/reaction/previews`:

  ```ts
  export type ComponentProductPreview = string | null;
  export type PreviewsById = Record<string, ComponentProductPreview>;
  export interface PreviewState { isLoading: boolean; svg: ComponentProductPreview }
  export type PreviewStatesById = Record<string, PreviewState>;
  /**
   * Renders molblocks to base64 SVGs, keyed as given; a null molblock, or one Indigo cannot
   * render, maps to null. Rejects if the renderer cannot start.
   */
  export function renderPreviews(
    molblocksById: PreviewsById,
    options?: { size?: number },
  ): Promise<PreviewsById>;
  ```

- Produces (module-internal, for tests): `createPreviewRenderer(createWorker: () => PreviewWorker)`.

- [ ] **Step 1: Branch**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c preview-renderer
cd frontend && npm ci
```

- [ ] **Step 2: Types and Indigo, copied**

```bash
cd ~/ord/ord-app/frontend
mkdir -p packages/ui/src/reaction/previews
cp apps/editor/src/store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts \
  packages/ui/src/reaction/previews/previews.types.ts
cp apps/editor/src/common/utils/indigo.ts packages/ui/src/reaction/previews/indigo.ts
cp apps/editor/src/common/utils/indigo.test.ts packages/ui/src/reaction/previews/indigo.test.ts
cp apps/editor/src/store/features/previewsWorker/worker.ts \
  packages/ui/src/reaction/previews/previews.worker.ts
cp apps/editor/src/store/features/previewsWorker/worker.test.ts \
  packages/ui/src/reaction/previews/previews.worker.test.ts
```

The editor keeps using its own copies until F2 deletes them; jscpd runs on the whole PR,
by which time only the package's remain. Fix the copies' imports to same-folder ones
(`./indigo.ts`, `./previews.types.ts`).

`packages/ui/package.json`:

```json
  "exports": {
    "./theme": "./src/theme/index.ts",
    "./theme/global.scss": "./src/theme/global.scss",
    "./display": "./src/display/index.ts",
    "./reaction/previews": "./src/reaction/previews/index.ts"
  },
  …
  "dependencies": {
    "buffer": "^6.0.3",
    "clsx": "^2.1.1",
    "indigo-ketcher": "1.43.0"
  },
```

`indigo-ketcher` is pinned to the version `ketcher-standalone@3.15.0` requires, so the
lockfile keeps one copy; check with
`jq -r '.packages | to_entries[] | select(.key | endswith("node_modules/indigo-ketcher")) | "\(.key) \(.value.version)"' package-lock.json`
after `npm install`, which must print a single 1.43.0 entry. Match `buffer` to the
editor's declared range.

```bash
cd ~/ord/ord-app/frontend && npm install
```

- [ ] **Step 3: Write the failing tests**

`src/reaction/previews/renderPreviews.test.ts`:

```ts
import { createPreviewRenderer, type PreviewWorker } from './renderPreviews.ts';

class FakeWorker implements PreviewWorker {
  posted: Array<unknown> = [];
  terminated = false;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  postMessage(message: unknown) {
    this.posted.push(message);
  }
  terminate() {
    this.terminated = true;
  }
  reply(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }
}

function setup() {
  const workers: Array<FakeWorker> = [];
  const render = createPreviewRenderer(() => {
    const worker = new FakeWorker();
    workers.push(worker);
    return worker;
  });
  return { render, workers };
}

describe('renderPreviews', () => {
  it('starts no worker when there is nothing to render', async () => {
    const { render, workers } = setup();
    await expect(render({})).resolves.toEqual({});
    await expect(render({ a: null })).resolves.toEqual({ a: null });
    expect(workers).toHaveLength(0);
  });

  it('starts one worker and matches each reply to its request', async () => {
    const { render, workers } = setup();
    const first = render({ a: 'MOL A' });
    const second = render({ b: 'MOL B' }, { size: 80 });
    expect(workers).toHaveLength(1);
    expect(workers[0].posted).toEqual([
      { id: 0, molblocksById: { a: 'MOL A' }, size: 120 },
      { id: 1, molblocksById: { b: 'MOL B' }, size: 80 },
    ]);
    workers[0].reply({ id: 1, svgsById: { b: 'SVG B' } });
    workers[0].reply({ id: 0, svgsById: { a: 'SVG A' } });
    await expect(first).resolves.toEqual({ a: 'SVG A' });
    await expect(second).resolves.toEqual({ b: 'SVG B' });
  });

  it('rejects a request the worker could not render', async () => {
    const { render, workers } = setup();
    const request = render({ a: 'MOL A' });
    workers[0].reply({ id: 0, error: 'Indigo did not load' });
    await expect(request).rejects.toThrow('Indigo did not load');
  });

  it('rejects every pending request when the worker fails, and starts a new one next time', async () => {
    const { render, workers } = setup();
    const request = render({ a: 'MOL A' });
    workers[0].onerror?.({ message: 'script error' } as ErrorEvent);
    await expect(request).rejects.toThrow('script error');
    expect(workers[0].terminated).toBe(true);
    void render({ b: 'MOL B' });
    expect(workers).toHaveLength(2);
  });

  it('ignores a reply with no pending request', () => {
    const { render, workers } = setup();
    void render({ a: 'MOL A' });
    expect(() => workers[0].reply({ id: 99, svgsById: {} })).not.toThrow();
  });
});
```

`src/reaction/previews/previews.worker.test.ts` (the copy of the editor's worker test):
change the mocked module to `./indigo.ts` and the side-effect import to
`./previews.worker.ts`, and change its message cases to the request protocol:

- non-object data and `null` are ignored, as today;
- `{ id: 3, molblocksById: { a: 'X', b: null }, size: 80 }` posts
  `{ id: 3, svgsById: { a: '<svg>X</svg>', b: '<svg>null</svg>' } }` (the stub renders
  whatever it is given; the real `renderSvg` returns null for null) and calls the stub
  with `size` 80;
- when `waitForIndigo` rejects, it posts `{ id: 3, error: 'Error: no wasm' }`.

```bash
cd ~/ord/ord-app/frontend/packages/ui && npx vitest run src/reaction/previews
```

Expected: FAIL — `renderPreviews.ts` does not exist; the worker still speaks the old
protocol.

- [ ] **Step 4: The worker**

`previews.worker.ts`:

```ts
import type { PreviewsById } from './previews.types.ts';
import { initIndigo, renderSvg, waitForIndigo } from './indigo.ts';

export interface PreviewsRequest {
  id: number;
  molblocksById: PreviewsById;
  size: number;
}

export type PreviewsReply =
  | { id: number; svgsById: PreviewsById }
  | { id: number; error: string };

initIndigo();

function isRequest(data: unknown): data is PreviewsRequest {
  // typeof null === 'object', so null needs its own check.
  return typeof data === 'object' && data !== null && 'id' in data && 'molblocksById' in data;
}

onmessage = (event: MessageEvent<unknown>) => {
  if (!isRequest(event.data)) {
    return;
  }
  const { id, molblocksById, size } = event.data;
  waitForIndigo().then(
    () => {
      const svgsById = Object.fromEntries(
        Object.entries(molblocksById).map(([key, molblock]) => [key, renderSvg(molblock, size)]),
      );
      postMessage({ id, svgsById } satisfies PreviewsReply);
    },
    (error: unknown) => {
      postMessage({ id, error: String(error) } satisfies PreviewsReply);
    },
  );
};
```

- [ ] **Step 5: The renderer**

`renderPreviews.ts`:

```ts
import type { PreviewsById } from './previews.types.ts';
import type { PreviewsReply, PreviewsRequest } from './previews.worker.ts';

const DEFAULT_SIZE = 120;

/** The part of a Worker the renderer uses. */
export interface PreviewWorker {
  postMessage(message: PreviewsRequest): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<PreviewsReply>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}

interface Pending {
  resolve: (svgsById: PreviewsById) => void;
  reject: (error: Error) => void;
}

function nullsFor(molblocksById: PreviewsById): PreviewsById {
  return Object.fromEntries(Object.keys(molblocksById).map(key => [key, null]));
}

/** A renderer over one worker, created on first use and replaced if it fails. */
export function createPreviewRenderer(createWorker: () => PreviewWorker) {
  let worker: PreviewWorker | undefined;
  let nextId = 0;
  const pending = new Map<number, Pending>();

  function settle(reply: PreviewsReply) {
    const request = pending.get(reply.id);
    if (!request) {
      return;
    }
    pending.delete(reply.id);
    if ('error' in reply) {
      request.reject(new Error(reply.error));
    } else {
      request.resolve(reply.svgsById);
    }
  }

  function failAll(message: string) {
    for (const request of pending.values()) {
      request.reject(new Error(message));
    }
    pending.clear();
    worker?.terminate();
    worker = undefined;
  }

  function getWorker(): PreviewWorker {
    if (!worker) {
      worker = createWorker();
      worker.onmessage = event => settle(event.data);
      worker.onerror = event => failAll(event.message);
    }
    return worker;
  }

  return function renderPreviews(
    molblocksById: PreviewsById,
    { size = DEFAULT_SIZE }: { size?: number } = {},
  ): Promise<PreviewsById> {
    if (Object.values(molblocksById).every(molblock => molblock === null)) {
      return Promise.resolve(nullsFor(molblocksById));
    }
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      getWorker().postMessage({ id, molblocksById, size });
    });
  };
}

/** Renders molblocks to base64 SVGs in one shared worker; see `createPreviewRenderer`. */
export const renderPreviews = createPreviewRenderer(
  () =>
    new Worker(new URL('./previews.worker.ts', import.meta.url), {
      type: 'module',
    }) as PreviewWorker,
);
```

`index.ts`:

```ts
export type {
  ComponentProductPreview,
  PreviewsById,
  PreviewState,
  PreviewStatesById,
} from './previews.types.ts';
export { renderPreviews } from './renderPreviews.ts';
```

- [ ] **Step 6: Run the package's tests and coverage**

```bash
cd ~/ord/ord-app/frontend/packages/ui && npx vitest run --coverage 2>&1 | tail -20
```

Expected: PASS. The floors are 100% branches: if a branch in the new code is uncovered,
add the test that covers it rather than lowering the floor. `indigo.ts`'s WASM paths
cannot run under Vitest (its test covers the two null guards); exclude it from coverage
in `vitest.config.ts` with a comment saying so, the way the editor excluded nothing for
it before only because its floors were lower.

- [ ] **Step 7: Commit**

```bash
cd ~/ord/ord-app
git add frontend/packages/ui frontend/package-lock.json
git commit -F "$SCRATCH/f1-msg.txt"   # "Add the preview renderer to the shared package"
```

### Task F2: The editor renders previews through `renderPreviews`

**Files:**

- Modify: `store/features/previewsWorker/previewsWorkerMiddleware.ts`, `previewsWorkerMiddleware.test.ts`
- Modify: `core/AppRoot.tsx`
- Modify: `features/reactions/ReactionEntities/entityFormConfiguration/components/CustomIdentifiers/MolblockIdentifier/DisplayMolblockPreview.tsx`
- Create: `…/MolblockIdentifier/DisplayMolblockPreview.test.tsx`
- Modify: `frontend/apps/editor/vite.config.ts` (`optimizeDeps.entries`)
- Modify: `store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts` (re-export)
- Delete: `common/utils/indigo.ts`, `common/utils/indigo.test.ts`,
  `store/features/previewsWorker/worker.ts`, `store/features/previewsWorker/worker.test.ts`

**Interfaces:**

- Consumes: `renderPreviews` and the preview types (F1).

- [ ] **Step 1: Write the failing tests**

`previewsWorkerMiddleware.test.ts`: replace the Worker harness with a mock of the
renderer, keep the existing action fixtures, and assert:

```ts
const { renderPreviewsMock } = vi.hoisted(() => ({ renderPreviewsMock: vi.fn() }));
vi.mock('@open-reaction-database/ui/reaction/previews', () => ({
  renderPreviews: renderPreviewsMock,
}));

function run(action: unknown) {
  const dispatch = vi.fn();
  const next = vi.fn((passed: unknown) => passed);
  previewsWorkerMiddleware({ dispatch, getState: vi.fn() } as unknown as MiddlewareAPI)(next)(
    action as UnknownAction,
  );
  return { dispatch, next };
}
```

- a single-reaction success renders `action.payload.previews`; a list success renders
  the merged map; all-templates renders the merged map (the existing cases, now on
  `renderPreviewsMock`'s arguments);
- when the render resolves with `{ a: 'SVG' }`, the middleware dispatches
  `setPreviewsByIds({ a: 'SVG' })` (`await vi.waitFor(() => expect(dispatch).toHaveBeenCalledWith(…))`);
- when it rejects, the middleware dispatches `setPreviewsByIds({ a: null })` for the
  requested keys, so the spinners stop;
- a thunk and an unrelated action pass through and render nothing.

`DisplayMolblockPreview.test.tsx`:

```tsx
const { renderPreviewsMock } = vi.hoisted(() => ({ renderPreviewsMock: vi.fn() }));
vi.mock('@open-reaction-database/ui/reaction/previews', () => ({
  renderPreviews: renderPreviewsMock,
}));

const identifier = (value: string) =>
  ({ value, details: 'drawn', type: 'MOLBLOCK' }) as unknown as ReactionCompoundIdentifier;

describe('DisplayMolblockPreview', () => {
  it('shows the rendered molblock at 80 px', async () => {
    renderPreviewsMock.mockResolvedValue({ molblock: 'PHN2Zz4=' });
    const { findByRole } = renderWithMantine(<DisplayMolblockPreview identifier={identifier('MOL')} />);
    expect(await findByRole('img', { name: 'drawn' })).toHaveAttribute(
      'src',
      'data:image/svg+xml;base64,PHN2Zz4=',
    );
    expect(renderPreviewsMock).toHaveBeenCalledWith({ molblock: 'MOL' }, { size: 80 });
  });

  it('shows nothing when the molblock cannot be rendered', async () => {
    renderPreviewsMock.mockRejectedValue(new Error('no wasm'));
    const { queryByRole } = renderWithMantine(<DisplayMolblockPreview identifier={identifier('MOL')} />);
    await vi.waitFor(() => expect(renderPreviewsMock).toHaveBeenCalled());
    expect(queryByRole('img')).not.toBeInTheDocument();
  });
});
```

Run both. Expected: FAIL.

- [ ] **Step 2: The middleware**

```ts
function molblocksIn(action: UnknownAction): PreviewsById | undefined {
  if (singleReactionActionsMatcher(action)) {
    return action.payload.previews;
  }
  if (getAllTemplatesActions.success.match(action)) {
    return action.payload.reduce((acc, template) => ({ ...acc, ...template.previews }), {});
  }
  if (multipleReactionsActionsMatcher(action)) {
    return action.payload.items.reduce((acc, reaction) => ({ ...acc, ...reaction.previews }), {});
  }
  return undefined;
}

function withoutPreviews(molblocksById: PreviewsById): PreviewsById {
  return Object.fromEntries(Object.keys(molblocksById).map(key => [key, null]));
}

/** Renders the previews of reactions and templates as they arrive, and stores the SVGs. */
export const previewsWorkerMiddleware: Middleware<object, AppState> = api => next => action => {
  if (typeof action === 'function') {
    return next(action);
  }
  const molblocksById = molblocksIn(action as UnknownAction);
  if (molblocksById) {
    renderPreviews(molblocksById).then(
      svgsById => api.dispatch(setPreviewsByIds(svgsById)),
      // A failed render still ends the loading state; the previews show as missing.
      () => api.dispatch(setPreviewsByIds(withoutPreviews(molblocksById))),
    );
  }
  return next(action);
};
```

Keep the two matchers as they are; let TypeScript narrow `action` the way today's code
does (adjust the casts to what `tsc -b` accepts).

- [ ] **Step 3: The molblock preview renders asynchronously**

`DisplayMolblockPreview.tsx`:

```tsx
export const DisplayMolblockPreview = memo(function DisplayMolblockPreview({
  identifier,
}: Readonly<DisplayMolblockPreviewProps>) {
  const { value: molblock, details, type } = identifier;
  const [svg, setSvg] = useState<string | null>(null);

  useEffect(() => {
    setSvg(null);
    if (!molblock) {
      return;
    }
    // A newer molblock supersedes a render still in flight.
    let isCurrent = true;
    renderPreviews({ molblock }, { size: 80 }).then(
      svgsById => {
        if (isCurrent) setSvg(svgsById.molblock ?? null);
      },
      () => {
        if (isCurrent) setSvg(null);
      },
    );
    return () => {
      isCurrent = false;
    };
  }, [molblock]);

  return svg ? (
    <Flex className={classes.previewWrapper} justify="center">
      <img className={classes.preview} alt={details ?? type} src={`data:image/svg+xml;base64,${svg}`} />
    </Flex>
  ) : null;
});
```

- [ ] **Step 4: Indigo leaves the main thread; the dev server finds the worker**

`core/AppRoot.tsx`: delete the `initIndigo` import and call.

`vite.config.ts`: the dev server pre-bundles what it finds by crawling `optimizeDeps.entries`;
the worker now lives in the package, so add it:

```ts
  optimizeDeps: {
    entries: ['index.html', 'src/**/worker.ts', '../../packages/ui/src/**/*.worker.ts'],
  },
```

and update the comment above it to name both places. Verify with a cold dev server: run
the e2e stack (`scripts/dev-e2e.sh`), delete `apps/editor/node_modules/.vite`, open a
reaction page in Playwright (`npx playwright test e2e/reactionPage.spec.ts`), and check
the dev server's log has no "new dependencies optimized" / "reloading" line after the
first page load. If Vite ignores the entry outside its root, keep it and add
`indigo-ketcher` and `buffer` to `optimizeDeps.include` instead.

- [ ] **Step 5: Delete the editor's copies**

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
git rm common/utils/indigo.ts common/utils/indigo.test.ts \
  store/features/previewsWorker/worker.ts store/features/previewsWorker/worker.test.ts
```

Replace the body of `store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts`
with a re-export, so its importers do not change:

```ts
export type {
  ComponentProductPreview,
  PreviewsById,
  PreviewState,
  PreviewStatesById,
} from '@open-reaction-database/ui/reaction/previews';
```

- [ ] **Step 6: Run everything**

```bash
cd ~/ord/ord-app/frontend && npm run typecheck && npm run lint
cd apps/editor && npx vitest run 2>&1 | tail -5
cd ../../packages/ui && npx vitest run 2>&1 | tail -5
grep -rn "common/utils/indigo\|initIndigo\|renderSvg" ~/ord/ord-app/frontend/apps/editor/src
```

Expected: PASS; the grep prints nothing.

- [ ] **Step 7: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src frontend/apps/editor/vite.config.ts
git commit -F "$SCRATCH/f2-msg.txt"   # "Render previews through the shared renderer"
```

### Task F3: The static source renders its previews

**Files:**

- Modify: `features/reactions/provider/staticReactionSource.ts`, `staticReactionSource.test.ts`

**Interfaces:**

- Produces: `createStaticReactionSource(snapshot, previews?)` — given `previews`, as
  today; without them, previews start loading (or missing, for a null molblock), the
  first subscription renders them, and subscribers are notified when they arrive.
  `getPreviews()` returns the same object between changes.

- [ ] **Step 1: Write the failing tests**

In `staticReactionSource.test.ts`:

```ts
const { renderPreviewsMock } = vi.hoisted(() => ({ renderPreviewsMock: vi.fn() }));
vi.mock('@open-reaction-database/ui/reaction/previews', () => ({
  renderPreviews: renderPreviewsMock,
}));

const withMolblocks = {
  ...snapshot,   // the file's existing fixture
  previews: { a: 'MOL A', b: null },
} as ReactionSnapshot;

describe('a static source without given previews', () => {
  it('starts with previews loading, renders them on first subscription, and notifies', async () => {
    renderPreviewsMock.mockResolvedValue({ a: 'SVG A', b: null });
    const source = createStaticReactionSource(withMolblocks);
    const before = source.getPreviews();
    expect(before).toEqual({ a: { isLoading: true, svg: null }, b: { isLoading: false, svg: null } });
    expect(source.getPreviews()).toBe(before);
    expect(renderPreviewsMock).not.toHaveBeenCalled();

    const listener = vi.fn();
    source.subscribe(listener);
    source.subscribe(vi.fn());
    expect(renderPreviewsMock).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(1));
    expect(source.getPreviews()).toEqual({
      a: { isLoading: false, svg: 'SVG A' },
      b: { isLoading: false, svg: null },
    });
  });

  it('stops loading when the render fails', async () => {
    renderPreviewsMock.mockRejectedValue(new Error('no wasm'));
    const source = createStaticReactionSource(withMolblocks);
    const listener = vi.fn();
    source.subscribe(listener);
    await vi.waitFor(() => expect(listener).toHaveBeenCalled());
    expect(source.getPreviews().a).toEqual({ isLoading: false, svg: null });
  });

  it('stops notifying after unsubscribing', async () => {
    renderPreviewsMock.mockResolvedValue({ a: 'SVG A', b: null });
    const source = createStaticReactionSource(withMolblocks);
    const listener = vi.fn();
    source.subscribe(listener)();
    await vi.waitFor(() => expect(source.getPreviews().a.svg).toBe('SVG A'));
    expect(listener).not.toHaveBeenCalled();
  });
});
```

Run: expected FAIL.

- [ ] **Step 2: Implement**

```ts
function loadingStates(molblocksById: PreviewsById): PreviewStatesById {
  return Object.fromEntries(
    Object.entries(molblocksById).map(([key, molblock]) => [
      key,
      { isLoading: molblock !== null, svg: null },
    ]),
  );
}

function renderedStates(svgsById: PreviewsById): PreviewStatesById {
  return Object.fromEntries(
    Object.entries(svgsById).map(([key, svg]) => [key, { isLoading: false, svg }]),
  );
}

/**
 * Creates a source over a reaction that never changes, such as one shown read-only. Without
 * `previews`, it renders the snapshot's molblocks when first subscribed to.
 */
export function createStaticReactionSource(
  snapshot: ReactionSnapshot | undefined,
  previews?: PreviewStatesById,
): ReactionSource {
  if (previews) {
    return {
      getSnapshot: () => snapshot,
      getPreviews: () => previews,
      subscribe: () => unsubscribe,
    };
  }
  const molblocksById = snapshot?.previews ?? {};
  let current = loadingStates(molblocksById);
  let isRendering = false;
  const listeners = new Set<() => void>();
  const show = (next: PreviewStatesById) => {
    current = next;
    listeners.forEach(listener => listener());
  };
  return {
    getSnapshot: () => snapshot,
    getPreviews: () => current,
    subscribe: listener => {
      listeners.add(listener);
      if (!isRendering) {
        isRendering = true;
        renderPreviews(molblocksById).then(
          svgsById => show(renderedStates(svgsById)),
          () => show(renderedStates(Object.fromEntries(Object.keys(molblocksById).map(key => [key, null])))),
        );
      }
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
```

`NO_PREVIEWS` goes away; an empty snapshot renders nothing and `renderPreviews({})`
resolves at once without a worker, so the hook and contract tests, whose snapshots
carry `previews: {}`, are unaffected. Run the provider tests and the contract suite.
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider/staticReactionSource.ts \
  frontend/apps/editor/src/features/reactions/provider/staticReactionSource.test.ts
git commit -F "$SCRATCH/f3-msg.txt"   # "Render a static source's previews when it is first used"
```

### Task F4: Open PR F

Full check and local Playwright as in B9 (the page and drawer screenshots must still
match in CI, since the SVGs come from the same renderer at the same size), then
`gh pr create --title "Make the preview renderer a module in the shared package" --body-file "$SCRATCH/f-body.md"`.

Notes in the body:

- One preview worker per page load, however many stores or sources exist; Indigo no
  longer loads on the main thread.
- Previews that fail to render stop spinning and show as missing.
- The drawer's molblock preview renders asynchronously, so it no longer shows a broken
  image when Indigo had not loaded yet.
- The editor still builds a second store at module scope for its `AppState` type
  (`store/configureAppStore.ts`), which still starts a second enumeration worker. Out
  of scope here.

---

## G: the move into `packages/ui`, in three PRs

After E, nothing in the reaction view reads the store, so G moves files and rewrites
imports. It is bigger than the design's "~60 moved": about 230 source files
(20,200 lines), 46 stylesheets, 41 icons, and 134 test files, counting the clean
`common/` modules the view depends on. It splits where the reviews differ:

| PR | Branch | Moves | Exports added |
| --- | --- | --- | --- |
| G1 | `shared-reaction-model` | the `AppReaction` model and converters, the provider, the test helpers | `./reaction/model`, `./reaction`, `./testing` |
| G2 | `shared-reaction-view` | the sections, previews, cards, header, validation, drawer and forms, icons, and their `common/` dependencies | `./reaction` grows; `./theme` gains the icons; `./display` gains the shared controls |
| G3 | `shared-shell` | `PageContainer`, `Breadcrumbs`, `Footer`, the logo | `./shell` |

The model gets its own subpath because the editor's enumeration worker imports
converters: a barrel that also exported components would pull React and stylesheets into
a worker.

### Task G0: The move script (scratch, not committed)

Every G task moves files with `git mv` and rewrites the imports that named them. Do it
with one script, kept in `$SCRATCH`, so each move is reproducible and reviewable as
"renames plus import lines".

`$SCRATCH/move-modules.mjs`:

```js
// Moves files and rewrites every import, re-export, dynamic import, and vi.mock that names
// them. Usage: node move-modules.mjs <mapping.json>, from ~/ord/ord-app/frontend.
// mapping.json: { "moves": { "<old path>": "<new path>" }, "barrels": { "<package dir>": "<subpath>" } }
// Paths are relative to frontend/. Package files import moved files as #<path>; editor files
// import them through the barrel whose directory holds the target.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const EDITOR_SRC = 'apps/editor/src';
const PACKAGE_SRC = 'packages/ui/src';
const SPECIFIER = /(\bfrom\s+|\bimport\s+|\bimport\(\s*|\bvi\.mock\(\s*|\bimportActual\(\s*)(['"])([^'"]+)\2/g;
const EXTENSIONS = ['', '.ts', '.tsx', '/index.ts', '/index.tsx'];

const { moves, barrels } = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const movedFrom = Object.fromEntries(Object.entries(moves).map(([from, to]) => [to, from]));

function walk(dir) {
  return readdirSync(dir).flatMap(name => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === 'node_modules' ? [] : walk(full);
    return /\.(ts|tsx|mjs)$/.test(name) ? [full] : [];
  });
}

function resolveOld(specifier, oldFile) {
  let base;
  if (specifier.startsWith('.')) base = path.join(path.dirname(oldFile), specifier);
  else if (specifier.startsWith('#')) base = path.join(PACKAGE_SRC, specifier.slice(1));
  else if (oldFile.startsWith(EDITOR_SRC)) base = path.join(EDITOR_SRC, specifier);
  else return undefined;
  return EXTENSIONS.map(ext => base + ext).find(candidate => candidate in moves || existsSync(candidate));
}

function barrelFor(target) {
  const dir = Object.keys(barrels)
    .filter(prefix => target.startsWith(prefix + '/'))
    .sort((a, b) => b.length - a.length)[0];
  if (!dir) throw new Error(`No barrel exports ${target}`);
  return barrels[dir];
}

function rewrite(file, specifier, target, warnings, kind) {
  if (!file.startsWith(PACKAGE_SRC) && /\.(s?css|png|svg)$/.test(target)) {
    warnings.push(`${file}: imports moved asset ${target}; export what it needs from the package`);
    return specifier;
  }
  if (file.startsWith(PACKAGE_SRC)) {
    if (path.dirname(file) === path.dirname(target)) return './' + path.basename(target);
    return '#' + path.relative(PACKAGE_SRC, target);
  }
  if (kind.includes('mock')) warnings.push(`${file}: vi.mock('${specifier}') now mocks the whole barrel`);
  return barrelFor(target);
}

for (const [from, to] of Object.entries(moves)) {
  mkdirSync(path.dirname(to), { recursive: true });
  execFileSync('git', ['mv', from, to]);
}

const warnings = [];
for (const file of [...walk(EDITOR_SRC), ...walk(PACKAGE_SRC)]) {
  const oldFile = movedFrom[file] ?? file;
  const source = readFileSync(file, 'utf8');
  const updated = source.replace(SPECIFIER, (match, kind, quote, specifier) => {
    const resolved = resolveOld(specifier, oldFile);
    if (resolved && resolved in moves) {
      return `${kind}${quote}${rewrite(file, specifier, moves[resolved], warnings, kind)}${quote}`;
    }
    if (file.startsWith(PACKAGE_SRC) && resolved?.startsWith(EDITOR_SRC)) {
      warnings.push(`${file}: imports editor file ${resolved}`);
    }
    if (file.startsWith(PACKAGE_SRC) && specifier.startsWith('../')) {
      warnings.push(`${file}: relative import ${specifier}`);
    }
    return match;
  });
  if (updated !== source) writeFileSync(file, updated);
}
console.log(warnings.length ? warnings.join('\n') : 'No warnings.');
```

Every warning is work: a package file that imports an editor file means a dependency is
missing from the mapping (add it, or cut the dependency), and a whole-barrel `vi.mock`
must become a partial mock
(`vi.mock(barrel, async importActual => ({ ...(await importActual()), name: vi.fn() }))`).
The script does not touch `@open-reaction-database/ui/…` self-imports inside moved
files; rewrite those to `#theme/index.ts` / `#display/index.ts` by hand (the package lint
rejects them).

After running it, `npm run typecheck` and `npm run lint` from `frontend/` find what is
left. Try each mapping on a throwaway branch first, read `git diff --stat`, then switch
back and delete the branch.

---

## PR G1: the model, the provider, and the test helpers

Branch `shared-reaction-model`, from `main` after E and F merge.

### Task G1.1: Separate what moves from what stays, inside the editor

No file moves yet; each change is a split or an import re-point, verified by the
existing tests.

**Files:**

- Modify: `store/entities/reactions/reactions.types.ts`; create
  `store/entities/reactions/reactionsStore.types.ts` with the editor-only types
- Modify: `store/entities/templates/templates.types.ts`; create
  `store/entities/reactions/variableType.ts`
- Modify: `common/constants.ts`; create `common/reactionFormats.ts`
- Create: `store/entities/reactions/parseReactionList.ts`; modify `reactions.utils.ts`
- Modify: `common/utils/itemsById.ts` and any other moving file that imports the
  `common/types` barrel
- Create: `test/emptyReactionData.ts`; modify `test/renderInReactionView.tsx`
- Split: `store/entities/reactions/reactions.binpb.test.ts` (keep the
  `findNonSerializableValue` case in `reactions.serializable.test.ts`)

- [ ] **Step 1: Split the types**

`reactionsStore.types.ts` takes, from `reactions.types.ts`: `ReactionTemplate`,
`ReactionOrTemplate`, `ReactionId`, `UpdateReactionSuccessPayload`,
`ImportReactionFromFilePayload`, `RenameReactionPayload`, `UpdateReactionPayload`,
`AddEditReactionFieldPayload` (they need `Variable` or describe editor thunks).
`reactions.types.ts` keeps the model: `ReactionNodeEntity`, the converter types,
`ReactionSummary`, the validation types, `ReactionMolBlocks`, `AppReaction`,
`ReactionResponse`, `BaseReaction`, `DatasetReaction`. Fix importers with `tsc -b`'s
errors as the list.

`variableType.ts` takes the `VariableType` enum from `templates.types.ts`;
`templates.types.ts` imports it from there.

`common/reactionFormats.ts` takes `DATE_FORMAT`, `DATE_TIME_FORMAT`, `DOT_DELIMITER`, and
`MAX_DATA_FILE_SIZE` from `common/constants.ts`.

`parseReactionList` (it needs the editor's `Pages`) moves from `reactions.utils.ts` to
`parseReactionList.ts`; `reactions.thunks.ts` imports it from there.

Point every moving file's `common/types` barrel import at the specific module
(`common/types/pages.ts`, `common/types/store/utils.ts`, …). The barrel re-exports
Auth0 and Redux types and cannot enter the package.

`test/emptyReactionData.ts` takes `emptyReactionData()` out of the render helper, which
re-exports it for its current importers.

- [ ] **Step 2: Run everything and commit**

```bash
cd ~/ord/ord-app/frontend && npm run typecheck && npm run lint
cd apps/editor && npx vitest run 2>&1 | tail -5
cd ~/ord/ord-app && git add frontend/apps/editor/src && git commit -F "$SCRATCH/g11-msg.txt"
# "Separate the reaction model from the editor's store types"
```

Expected: PASS, same counts plus the split test file.

### Task G1.2: Move the model

**Files:** the mapping below; `packages/ui/package.json`, `packages/ui/src/reaction/model/index.ts`.

**Interfaces:**

- Produces: `@open-reaction-database/ui/reaction/model`, which exports the model types,
  converters, models, utilities (`getDeepReactionPart`, `deepMergeWithArrayMerge`,
  `generateDeepPartialReactionByPath`, `parseReaction`, `parseValidation`,
  `getReactionPreviews`, `reactionFlatPathToSidebars`, …), `VariableType`,
  `ReactionPathComponents`, and the formats.

- [ ] **Step 1: The mapping**

Generate `$SCRATCH/g12.json` rather than typing 70 paths: everything tracked under
`store/entities/reactions/` except what belongs to the store, plus the model's
dependencies elsewhere. `$SCRATCH/g12-mapping.mjs`:

```js
// Writes the G1.2 mapping: the reaction model and its tests, into packages/ui/src/reaction/model.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const FROM = 'apps/editor/src/';
const TO = 'packages/ui/src/reaction/model/';
const REACTIONS = 'store/entities/reactions/';
// The store's own modules, and what G1.1 split out for the editor.
const STAYS =
  /^(reactions\.(actions|reducer|selectors|thunks)|reduxReactionSource|reactionSourceContract|parseReactionList|reactionsStore\.types|reactions\.serializable)\.|^reactionsPreviews\/|^reactionsInputs\/reactionInputs\.(actions|thunks)\./;
const EXTRA = {
  'store/utils/clearDependantFields.ts': 'utils/clearDependantFields.ts',
  'store/utils/clearDependantFields.test.ts': 'utils/clearDependantFields.test.ts',
  'store/utils/replaceNameIdInReactionComponentPath.ts': 'utils/replaceNameIdInReactionComponentPath.ts',
  'store/utils/replaceNameIdInReactionComponentPath.test.ts': 'utils/replaceNameIdInReactionComponentPath.test.ts',
  'common/utils/date.ts': 'utils/date.ts',
  'common/utils/date.test.ts': 'utils/date.test.ts',
  'common/utils/itemsById.ts': 'utils/itemsById.ts',
  'common/utils/itemsById.test.ts': 'utils/itemsById.test.ts',
  'common/utils/reversePrimitiveRecord.ts': 'utils/reversePrimitiveRecord.ts',
  'common/utils/reversePrimitiveRecord.test.ts': 'utils/reversePrimitiveRecord.test.ts',
  'common/types/reaction/reactionPathComponents.ts': 'reactionPathComponents.ts',
  'common/types/selectOptions.ts': 'selectOptions.ts',
  'common/reactionFormats.ts': 'reactionFormats.ts',
  'features/reactions/provider/getDeepReactionPart.ts': 'getDeepReactionPart.ts',
};

const tracked = execFileSync('git', ['ls-files', FROM + REACTIONS], { encoding: 'utf8' })
  .trim()
  .split('\n')
  .map(file => file.slice((FROM + REACTIONS).length))
  .filter(file => !STAYS.test(file));
const moves = Object.fromEntries([
  ...tracked.map(file => [FROM + REACTIONS + file, TO + file]),
  ...Object.entries(EXTRA).map(([from, to]) => [FROM + from, TO + to]),
]);
const barrels = {
  'packages/ui/src/reaction/model': '@open-reaction-database/ui/reaction/model',
  'packages/ui/src/reaction/previews': '@open-reaction-database/ui/reaction/previews',
};
writeFileSync(process.argv[2], JSON.stringify({ moves, barrels }, null, 2));
console.log(`${Object.keys(moves).length} files`);
```

```bash
cd ~/ord/ord-app/frontend && node "$SCRATCH/g12-mapping.mjs" "$SCRATCH/g12.json"
```

Read the JSON before using it: every `store/entities/reactions` entry should be a
converter, model, type, transform, constant, or util (and its test). Drop any `EXTRA`
entry whose file does not exist (some `common/utils` modules may have no test). If
`getDeepReactionPart.ts` has a test in the provider folder, add it. Move
`common/utils/index.ts` too only if every module it re-exports moves; otherwise point
the moving files at the specific util in G1.1.

- [ ] **Step 2: Run the script, then write the barrel**

```bash
cd ~/ord/ord-app/frontend && node "$SCRATCH/move-modules.mjs" "$SCRATCH/g12.json"
```

`packages/ui/src/reaction/model/index.ts`: one `export * from './<file>';` per moved
non-test module. `tsc -b` reports a name exported twice as TS2308; replace that file's
`export *` with an explicit list that leaves the duplicate to its owner.

`packages/ui/package.json`:

```json
  "exports": {
    …,
    "./reaction/model": "./src/reaction/model/index.ts",
    "./reaction/previews": "./src/reaction/previews/index.ts"
  },
  "peerDependencies": {
    "@buf/open-reaction-database_ord-schema.bufbuild_es": "2.16.0-00000000000000-2a4e5a8d72a2.1",
    "@bufbuild/protobuf": "^2.16.0",
    …
  },
  "dependencies": {
    "@fastify/deepmerge": "^2.0.2",
    "dayjs": "^1.11.13",
    …
  },
```

Copy the exact version strings from `apps/editor/package.json`; the ORD SDK stays pinned
to its release (see `CLAUDE.md`). Add the two peers to `devDependencies` too, so the
package's tests resolve them. `npm install` from `frontend/`; the lockfile diff must add
no new versions.

- [ ] **Step 3: Check**

```bash
cd ~/ord/ord-app/frontend && npm run typecheck && npm run lint
cd apps/editor && npx vitest run 2>&1 | tail -5
cd ../../packages/ui && npx vitest run --coverage 2>&1 | tail -20
```

Expected: PASS; the editor's file count drops by the moved tests and the package's rises
by the same. Raise the package's floors to the new measured coverage, rounded down, and
lower the editor's only if its measured coverage fell below them (state both in the PR).

- [ ] **Step 4: The enumeration worker**

`store/features/enumerationWorker/worker.ts` now imports from
`@open-reaction-database/ui/reaction/model`. Build and confirm the worker chunk holds no
React: `npm run build -w apps/editor`, then
`grep -l "react-dom\|useState" apps/editor/dist/assets/worker-*.js` prints nothing for
the enumeration worker.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor frontend/packages/ui frontend/package-lock.json
git commit -F "$SCRATCH/g12-msg.txt"   # "Move the reaction model into the shared package"
```

### Task G1.3: Move the provider and the test helpers

**Files:** `features/reactions/provider/*` (and `drawer.ts`) →
`packages/ui/src/reaction/provider/`; the slot prop types
(`ReactionInteractions/ReactionValueLabel/reactionValueLabel.types.ts`,
`ReactionInteractions/ReactionViewDeleteButtons/reactionViewDeleteButtons.types.ts`) →
`packages/ui/src/reaction/provider/`; `features/reactions/provider/renderWithReaction.tsx`,
`test/emptyReactionData.ts`, `test/fullReaction.ts`, `test/fullReactionSnapshot.ts` →
`packages/ui/src/testing/`; `frontend/eslint.config.mjs`.

**Interfaces:**

- Produces: `@open-reaction-database/ui/reaction` (the provider, its hooks and types,
  `createStaticReactionSource`) and `@open-reaction-database/ui/testing`
  (`renderWithReaction`, `emptyReactionData`, `fullReaction`, `fullReactionSnapshot`).

- [ ] **Step 1: Map, move, export**

Mapping barrels: `packages/ui/src/reaction/provider` → `@open-reaction-database/ui/reaction`;
`packages/ui/src/testing` → `@open-reaction-database/ui/testing`. Run the script.

`packages/ui/src/reaction/index.ts` exports the provider's public surface (not
`equality.ts` or `orderInputs.ts`, which stay internal). `packages/ui/src/testing/index.ts`
exports the four helpers and the package's existing `renderWithMantine`.
`package.json`: `"./reaction": "./src/reaction/index.ts"`,
`"./testing": "./src/testing/index.ts"`; dependency `use-sync-external-store`, dev
dependency `@types/use-sync-external-store` (editor's versions).

`fullReactionSnapshot.ts` used the editor's `ordReactionToReaction`, which is now in the
model: the script rewrites it to `#reaction/model/reactions.converters.ts`.

- [ ] **Step 2: The lint block**

Delete the `apps/editor/src/features/reactions/provider/**` block from
`frontend/eslint.config.mjs`; the package block now holds the provider to the stricter
rule (no type imports from Redux either). If the provider type-imports anything from
the editor still, the script printed it: move that type into the model first.

- [ ] **Step 3: Check and commit**

As in G1.2 Step 3. Then:

```bash
cd ~/ord/ord-app
git add frontend
git status --short | grep -v '^R ' | head -40   # review everything that is not a rename
git commit -F "$SCRATCH/g13-msg.txt"   # "Move ReactionProvider and the test helpers into the shared package"
```

### Task G1.4: Open PR G1

Full check (B9), jscpd, local Playwright; push; open with
`gh pr create --title "Move the reaction model and provider into the shared package" --body-file "$SCRATCH/g1-body.md"`.
The body's Changes list the three new subpaths and the split files; Notes give the
before/after file and test counts for both workspaces and the coverage floors.

---

## PR G2: the reaction view and the drawer

Branch `shared-reaction-view`, from `main` after G1 merges.

### Task G2.1: Ketcher is an editor slot

The drawer imports the Ketcher editor statically. It is unreachable in read-only mode,
but any app that compiles the package would compile Ketcher, with the editor's
`process.env` define, `transformMixedEsModules`, and dependency overrides. It becomes an
optional slot the editor supplies.

**Files:**

- Modify: `packages/ui/src/reaction/provider/reactionProvider.types.ts` (slot)
- Modify: `features/reactions/ReactionEntities/entityFormConfiguration/components/CustomIdentifiers/CustomIdentifiers.tsx`
- Modify: `pages/ReactionPage/useDatasetReactionProviderProps.ts` (`EDITABLE_SLOTS`)
- Create: `…/CustomIdentifiers/CustomIdentifiers.ketcher.test.tsx`

**Interfaces:**

- Produces:

  ```ts
  export interface MoleculeEditorProps {
    opened: boolean;
    onClose: () => void;
    onSave: (identifier: Pick<ReactionCompoundIdentifier, 'value' | 'details'>) => void;
    identifier: Pick<ReactionCompoundIdentifier, 'value' | 'details'> | null;
  }
  // in ReactionSlots:
  /** Draws a molecule for a molblock identifier; without it, molblocks cannot be drawn. */
  MoleculeEditor?: FC<MoleculeEditorProps>;
  ```

- [ ] **Step 1: Write the failing test**

`CustomIdentifiers.ketcher.test.tsx` renders `CustomIdentifiers` at a component path in
an editable reaction, once with `slots: { MoleculeEditor: FakeEditor }` (a component
that renders "editor open" when `opened`) and once without: with the slot, clicking
"Add Molblock Identifier" shows "editor open"; without it, the button is absent. Mock
nothing else. Expected: FAIL (the slot type does not exist; the button always shows).

- [ ] **Step 2: Implement**

In `CustomIdentifiers.tsx`: `const { MoleculeEditor } = useReactionSlots();`, render the
"Add Molblock Identifier" column only when `MoleculeEditor` is present, and render
`{MoleculeEditor && <MoleculeEditor opened={componentsEditorOpened} onSave={onSaveMolblock} onClose={handleCloseKetcher} identifier={selectedMolblockIdentifier} />}`
in place of `<ComponentsKetcherEditor … />` (the same four props it receives today); delete
its import. Add
`MoleculeEditor: ComponentsKetcherEditor` to `EDITABLE_SLOTS`. `ComponentsKetcherEditor`
and its stylesheet stay in the editor. Run the test and the suite; commit
("Supply the molecule editor to the drawer as a slot").

### Task G2.2: Settings the view read from the editor's environment become props

`ReactionPreview` and `ReactionCard` read `showReactionPreviewDetails` from
`common/configuration.constants.ts`, which reads `import.meta.env.VITE_…`. The package
cannot read the editor's environment.

- [ ] **Step 1:** Add `showDetails?: boolean` to `ReactionPreview`, `ReactionCard`, and
  `ReactionHeader` (which passes it to its preview). Test each: with `showDetails` the
  conditions tooltip text / descriptor lists render; without, not (the existing tests
  cover the default).
- [ ] **Step 2:** The editor passes `showDetails={showReactionPreviewDetails}` from
  `DatasetReactionCard`, `TemplatesList.page`, `DatasetReactionHeader`, `TemplateHeader`,
  and `EnumerationSetup`. Run the suite; commit ("Pass the preview-details setting to the
  reaction view").

`grep -rn "configuration.constants" <every file the G2 mapping moves>` must print nothing
afterwards.

### Task G2.3: The view's tests render without Redux

The package's tests cannot build a Redux store. Before the move, the tests of every file
G2 moves switch from `renderInReactionView` / `renderWithProviders` to the package's
`renderWithReaction`, extended for what they need.

**Files:**

- Modify: `packages/ui/src/testing/renderWithReaction.tsx`
- Modify: every test of a file in G2's mapping that uses `renderInReactionView` or
  `renderWithProviders` (the inventory counts 57)

**Interfaces:**

- Produces: `renderWithReaction(ui, options)` with, beside today's options:
  `reaction?: AppReaction` (the snapshot's `data`, default `emptyReactionData()`),
  `record?: Partial<Omit<DatasetReaction, 'data'>>`, `pathComponents?` (sets
  `reactionEntityContext`, once that context is in the package; until G2.4, the editor
  test passes it by wrapping), `editable?: boolean` (supplies `stubReactionActions()`),
  and the export `stubReactionActions(): ReactionActions` (async no-ops built from
  `vi.fn()`; `testing/` may use devDependencies).

- [ ] **Step 1:** Extend `renderWithReaction` and test the extension in
  `packages/ui/src/testing/renderWithReaction.test.tsx` (a probe reading
  `useReactionSnapshot`, `useIsViewOnly`, and `useReactionActions` for each option).
- [ ] **Step 2:** Switch the tests, one directory at a time, running each directory after
  its switch. `renderInReactionView(…, { isViewOnly: true })` becomes
  `renderWithReaction(…, { reaction })`; the default editable case becomes
  `{ reaction, editable: true }`; `reactionId: 'template_1'` becomes
  `{ reactionId: 'template_1', isTemplate: true }`.
- [ ] **Step 3:** Tests that observed the editor's thunks through mocks now observe the
  actions: `ReactionEntityForm.paste.test.tsx` and `ReactionEntityForm.saveAndClose.test.tsx`
  assert `actions.update` was called with `(['provenance'], values)` and read
  `newValue` from `update.mock.calls[0][1]`; `buildUseCreate.test.tsx` asserts
  `actions.update(path, entity)` instead of the dispatched thunk; `ComponentsLookup.test.tsx`
  stubs `actions.addIdentifierByName` instead of axios; `UpdatePersonInfo.test.tsx` stubs
  `actions.currentPerson` instead of `selectSelf`. These are the changed assertions G2
  lists; each checks the same values as before.
- [ ] **Step 4:** Tests of editor-only files (the slots in `ReactionInteractions`, the
  header actions, `TemplateHeader`, the pages) keep `renderInReactionView`. Run the
  suite; commit ("Render the reaction view's tests without the editor's store").

### Task G2.4: Move the view

**Files:** the mapping; `packages/ui/{package.json,tsconfig.json,vitest.config.ts,README.md}`;
`packages/ui/src/reaction/index.ts`, `packages/ui/src/theme/index.ts`,
`packages/ui/src/display/index.ts`.

- [ ] **Step 1: The mapping**

Moves into `packages/ui/src/reaction/view/` (keep each folder's internal layout):

- `features/reactions/ReactionView/**`
- `common/components/ReactionPreview/**`, `common/components/ReactionCard/**`
- `features/reactions/ReactionHeader/ReactionHeader.tsx` and
  `ReactionHeader/ReactionValidationResult/**` (not `DatasetReactionHeader/`,
  `ReactionHeaderActions/`, or the download menu B5 may have extracted)
- `features/reactions/ReactionEntities/**`, except
  `…/CustomIdentifiers/ComponentsKetcherEditor/**`
- `features/reactions/ReactionDetailsSidebar/**`
- `features/reactions/ReactionValueLabelWrapper.tsx`
- From `features/reactions/ReactionInteractions/`: `ReactionNodeValidationResult/**`,
  `ReactionValueLabel/DatasetReactionValueLable.tsx`,
  `ReactionViewDeleteButtons/ReactionViewButton.tsx`,
  `ReactionViewDeleteButtons/reactionViewDeleteButtons.utils.ts`,
  `ReactionInteractions/ReactionEntityDelete` if it lives there (it lives in
  `ReactionEntities/`), and both straddling stylesheets
  (`reactionValueLabel.module.scss`, `reactionViewDeleteButtons.module.scss`), which the
  package exports as class maps (`reactionValueLabelClasses`,
  `reactionViewDeleteButtonsClasses`) for the editor's template label and Edit/Delete
  buttons.

Moves into `packages/ui/src/theme/icons/`: `common/icons/**` (all 41, so the icon set
stays one set). Moves into `packages/ui/src/display/`: the clean `common/` modules the
view uses (the inventory's G.4 table, rows marked clean, except `InputModal`,
`requiredTextField.schema.ts`, and `DownloadMenu`, which stay with the editor's header
actions), keeping their folder names.

Delete `features/reactions/ReactionHeader/reactionHeader.module.scss` (no importer).

Barrels: `packages/ui/src/reaction/view` → `@open-reaction-database/ui/reaction`;
`packages/ui/src/theme` → `@open-reaction-database/ui/theme`;
`packages/ui/src/display` → `@open-reaction-database/ui/display`.

- [ ] **Step 2: Toolchain for icons and the view's dependencies**

`packages/ui/package.json`: peers `@mantine/form`, `@mantine/dates`,
`@mantine/notifications`; dependencies `yup`, `mime`, `html-to-image`; dev dependency
`vite-plugin-svgr` (editor versions throughout). `tsconfig.json` `types` gains
`"vite-plugin-svgr/client"`. `vitest.config.ts`: `plugins: [react(), svgr()]`.

`packages/ui/README.md` gains "What a host provides": import
`@open-reaction-database/ui/theme/global.scss`, `@mantine/core/styles.css`,
`@mantine/dates/styles.css`, and `@mantine/notifications/styles.css`; mount
`<Notifications />`; add `svgr()` to its Vite plugins.

- [ ] **Step 3: Run the script; write the barrels; check**

Run `move-modules.mjs`. Add the moved components the editor uses to
`src/reaction/index.ts` (sections, `ReactionContent`, `ReactionTabs`, `ReactionPreview`,
`ReactionCard`, `ReactionHeader`, `ReactionDetailsSidebar`, the shared slots
`DatasetReactionValueLabel` and `ReactionViewButton`, `ReactionEntityDelete`,
`ReactionEntityBlock`, the class maps), the icons to `src/theme/index.ts`, and the
moved controls to `src/display/index.ts`. Fix every warning the script prints. Then the
full check (B9) and the package coverage, raising its floors to the new measured
values.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app
git add frontend
git status --short | grep -v '^R ' | head -60
git commit -F "$SCRATCH/g24-msg.txt"   # "Move the reaction view and drawer into the shared package"
```

### Task G2.5: Open PR G2

Push and open (`gh pr create --title "Move the reaction view into the shared package" --body-file "$SCRATCH/g2-body.md"`).
The three Playwright screenshots are the check that moving the stylesheets did not
reorder CSS; if one differs, compare the PNGs from the artifact, find the rule whose
order changed (cross-folder stylesheet imports are the likely ones: `ReactionHeader`
uses the card's module, `WorkupInput` uses `AuthenticStandard`'s, `ReactionEntityRow`
uses `reactionFormNode`'s), and fix the import order rather than the baseline. Notes:
the changed assertions from G2.3, the Ketcher slot, and the counts.

---

## PR G3: the shell

Branch `shared-shell`, from `main` after G2 merges.

### Task G3.1: `PageContainer` takes its header controls

**Files:** `common/components/PageContainer/PageContainer.tsx`, `PageContainer.test.tsx`,
and a new editor wrapper `common/components/PageContainer/EditorPageContainer.tsx`; the
six pages that render `PageContainer`.

- [ ] **Step 1: Failing test.** In `PageContainer.test.tsx`, drop the `UserMenu` mock and
  assert that `headerActions={<span>menu</span>}` renders in the header.
- [ ] **Step 2: Implement.**

  ```tsx
  interface PageContainerProps extends PropsWithChildren {
    breadcrumbs: Array<Breadcrumb>;
    badge?: ReactNode;
    /** Controls at the right of the header, such as the signed-in user's menu. */
    headerActions?: ReactNode;
  }
  ```

  render `{headerActions}` where `<UserMenu />` was, and delete the `UserMenu` import.
  `EditorPageContainer` renders `<PageContainer {...props} headerActions={<UserMenu />} />`;
  the six pages import it instead (a codemod of one import line each). Run, commit
  ("Let the page shell take its header controls").

### Task G3.2: Move the shell

- [ ] **Step 1:** Mapping: `PageContainer.tsx`, `PageContainer.module.scss`,
  `ORDLogo.png`, `Breadcrumbs/**`, `Footer/**`, and `common/types/breadcrumbs.ts` →
  `packages/ui/src/shell/`, barrel `@open-reaction-database/ui/shell`. The script moves
  only `.ts`/`.tsx` importers' references; move the `.png` and `.scss` files in the
  mapping too (it moves any path) and check `PageContainer.tsx`'s same-folder imports.
- [ ] **Step 2:** `package.json`: export `./shell`; `wouter` as a peer and dev
  dependency. `frontend/eslint.config.mjs`: a block for `packages/ui/src/shell/**` that
  repeats the package's `no-restricted-imports` patterns without `wouter`. Prove the
  rule: add `import 'wouter';` to a file in `src/reaction/`, see `npm run lint` fail,
  remove it.
- [ ] **Step 3:** Full check, local Playwright, commit ("Move the page shell into the
  shared package"), push, open PR G3.

### Task G3.3: Close out the step

In the logbook entry (`~/ord/ord-logbook/entries/2026-10-09-search-and-browse-inside-ord-app/`),
set the design's status to "done" with the list of PRs, and update the README's step 2
status. This is a logbook PR: arm auto-merge last, after confirming its files.

---

## Refinements to the design

These came from reading the code A left on `main` while planning; the design file has
been updated to match.

- **B through E run in order.** The design has B through F depending only on A. They
  touch the same files: the sections B moves also dispatch drawer changes (C) and edits
  (E), and the drawer forms D moves dispatch both. In order, each line changes once. F
  is independent of B through E.
- **The test harness moves first.** `renderInReactionView`, which 38 test files use,
  mounts the real `ReactionProvider` over a Redux source (B2). The provider supplies the
  same legacy values, so tests keep their assertions while components move to the
  hooks. The shared components' tests move to the package's `renderWithReaction` in G2,
  when they move.
- **Two more hooks.** `useIsTemplate()` (B), for the labels and buttons that differ on
  templates, and `useReactionId()` (D), the ID the host gave the provider, which the
  template slot uses to reach the template's variables. `ReactionEntityContext` drops
  its `reactionId`.
- **Links are a slot.** A crude component links to another reaction by ORD ID, and the
  editor finds that reaction by searching the active dataset, which is asynchronous.
  A `links.reaction(id): string | undefined` function cannot express that, so the
  provider takes an optional `ReactionLink` slot instead, and `useReactionLinks()` is
  dropped. Without the slot the ID shows as text.
- **The header's editor controls are props.** The host page renders the header itself,
  so `ReactionHeader` takes `actions` and `titleActions` props rather than reading a
  `HeaderActions` slot. The editor's `DatasetReactionHeader` supplies Remove, Save as
  Template, Download, the copy menu, and rename. `ReactionCard` already took its title
  and actions as props.
- **Every preview has a provider.** Besides the reaction and template pages: each
  dataset card, each template card, and the enumeration wizard's preview, which shows
  the template the form selects rather than the page's.
- **The drawer.** Thirteen files write the stack, not four, and the templates'
  Variables drawer closed itself by listening to the stack's actions; it now closes
  itself when a variable is clicked. The stack and its actions are separate contexts,
  so the many buttons that open forms do not re-render when the stack changes. wouter
  does not remount a page when only its parameters change, so the pages key the
  provider by reaction explicitly.
- **The actions.** `addIdentifierByName(identifiersPath, name): Promise<boolean>`
  replaces `lookupCompound(query): Promise<LookupResult>`: it resolves the name, appends
  the identifier as the thunk did, and reports whether the name resolved, so the
  "resolve even on failure" rule holds and the lookup can still say "Compound not
  found". `currentPerson?()` returns a provenance person. `reduxReactionActions` takes
  the store's `dispatch` and `getState`.
- **Templates lose the drawer's Delete icon too.** They are read-only, and the icon
  showed on them as on read-only datasets.
- **`reactionContext` is retired at the end of E**, when its last reader moves, not in
  G.
- **The preview renderer.** `renderPreviews(molblocksById, { size })` resolves to
  `PreviewsById` (a base64 SVG or null per key) and rejects when the worker cannot
  start; one lazily created worker serves every caller, with request IDs. The drawer's
  molblock preview renders through it too, so Indigo leaves the main thread, and failed
  renders end their spinners.
- **G is three PRs and about 230 files.** The model gets its own subpath,
  `./reaction/model`, which a worker can import without React or stylesheets. The
  Ketcher editor becomes an optional `MoleculeEditor` slot that the editor supplies,
  instead of a lazy import in the package: a lazy chunk would still make every app that
  compiles the package compile Ketcher. The preview-details setting, read from the
  editor's environment, becomes a prop. All 41 icons move into `./theme`, and the
  package exports the two class maps the editor's slots share.
- **The contract suite compares rendered HTML.** The full reaction renders over a static
  source with an empty store and over the Redux source; the HTML must match, so a
  component still reading the store fails. E adds the read-only check: no form shows an
  edit control without actions.
- **Playwright.** The dataset card's baseline is captured before B changes the card,
  from a draft PR. E's read-only check seeds its dataset by demoting the e2e user to
  viewer in the group the seed creates, since the no-auth stack has one user.
