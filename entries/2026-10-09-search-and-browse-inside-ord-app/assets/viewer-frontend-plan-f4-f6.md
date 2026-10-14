# The viewer's pages: F4–F6 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

**Goal:** Build the viewer's pages on the scaffold F1–F3 shipped: browse, datasets and
their charts, reactions, the selected set, and downloads (F4); search (F5); and `/ask`
(F6), each with unit tests and end-to-end tests against the real backend.

**Architecture:** Pages read the API through F2's TanStack Query hooks and render the
shared package's components. A reaction record becomes a read-only `ReactionProvider`
through a static source. The search form's state lives in the URL under ord-interface's
parameter names and compiles in the browser to a `Query`. Playwright runs against a
production build served by `vite preview`, proxying `/api` to the viewer's backend over
the derived fixture corpus.

**Tech Stack:** React 19, Vite 6, Mantine 7 with `@mantine/charts`, wouter 3, TanStack
Query 5, Vitest with happy-dom and Testing Library, Playwright 1.60; FastAPI and
`ord_schema.search` for the backend.

**Spec:** [`viewer-frontend-design.md`](viewer-frontend-design.md), with its
Refinements as F1–F3 recorded them in [`viewer-frontend-plan.md`](viewer-frontend-plan.md).
Paths are in ord-app at
[`9534224`](https://github.com/open-reaction-database/ord-app/commit/9534224), and
ord-interface at
[`1953940`](https://github.com/open-reaction-database/ord-interface/commit/1953940).

## What F1–F3 left to build on

- **API layer** (`frontend/apps/viewer/src/api/`):
  - `hooks.ts`: `REACTIONS_PER_REQUEST = 100`, `useDatasets()`,
    `useDataset(datasetId)`, `useCompounds(datasetId, side)`, `useReactions(reactionIds)`,
    `useReaction(reactionId)`, `useSearch(query | null)`, `useAsk(question | null)`;
  - `client.ts`: `ApiError` (`status`, `detail`, `fromBackend`), `errorMessage(error)`;
  - `download.ts`: `downloadReactions(reactionIds)`;
  - `types.ts`: `DatasetSummary`, `CompoundCount`, `CompoundSide`
    (`'inputs' | 'products'`), `ReactionRecord`, `Query`, `CompiledQuery`,
    `ReactionsResult`, `TableResult`, `SearchResult`, `AskResponse`.
- **Shell and routing:**
  - `ViewerPage({breadcrumbs, children})`, `NotFoundPage`, `AboutPage`;
  - `routes.tsx` with ord-interface's redirects;
  - `routeParam(value)` for wouter's half-decoded path parameters;
  - `renderAt(path, ui)` in `src/test/render.tsx`, which returns `history` and gives each
    render its own query cache.
- **Backend:** `python -m ord_viewer.testing <directory>` derives the fixture corpus.
  `ord_viewer.testing` has `make_client`, `offline_resolver` (which knows `pyridine`),
  and `DATASETS`:
  - `ord_dataset-viewer01`, "viewer one", with `ord-viewer0101` (a Suzuki coupling, 65%
    yield), `ord-viewer0102` (an acylation of L-alanine, 90%), and `ord-viewer0103`
    (an acylation of ethylamine, 75%);
  - `ord_dataset-viewer02`, "viewer two", with `ord-viewer0201` (the D-alanine
    acylation, 40%) and `ord-viewer0202` (an esterification, no yield, with a named
    catalyst).
- **Image:** `deploy/viewer` and `build_viewer_image`; nothing in F4–F6 changes them.

## Global Constraints

- Every source file starts with the Apache 2.0 header addlicense writes; new files carry
  `Copyright 2026`.
- The viewer imports its own files through `#…` (`"imports": {"#*": "./src/*"}`), never
  `../`, and the shared package only through its `exports`; no Redux, axios, or Auth0.
- American English in UI text, comments, and docs.
- Code comments say what the code does and why, never what changed.
- Give every `pytest.raises` a `match=`. Python follows Google-style docstrings, with no
  lazy imports.
- Type-check with `npm run typecheck` (`tsc -b`) from `frontend/`; lint with
  `npm run lint:check`.
- Coverage floors in `frontend/apps/viewer/vite.config.ts` rise to the measured value,
  rounded down, at the end of each PR.
- The viewer's unit tests run with `npx vitest run` in `frontend/apps/viewer`; the
  backend's with `uv run pytest -n auto` in `backend/viewer`.
- Each PR comes from an up-to-date `main`, green on its own: F4, then F5, then F6.

## Review Focus

1. **An ID the corpus does not hold.** `/datasets/<unknown>` and `/reactions/<unknown>`
   show NotFound, not an error or an endless loader (F4.5, F4.6: `DatasetPage.test.tsx`,
   `ReactionPage.test.tsx`).
2. **A selected set past its bound, or with repeats.** `/reactions?id=…` with 120 IDs
   shows the first 100 and says so; a repeated ID shows once, in the order first given
   (F4.7: `ReactionSetPage.test.tsx`).
3. **The backend starting or down.** Every page shows `errorMessage`'s sentence, never a
   blank page, when a hook fails (F4.3: `ErrorNotice.test.tsx`; and one test per page).
4. **A legacy search URL whose SMARTS holds `;`.** `component=[C;R]Cl;input;smarts`
   splits from the right, as ord-interface's backend does (F5.1: `form.test.ts`).
5. **A dataset with no compounds.** A chart with nothing to draw says so rather than
   drawing empty axes (F4.5: `CompoundChart.test.tsx`).

## Refinements to the design

These came from reading ord-app at `9534224` and ord-interface at `1953940` while
planning; the design file is updated to match.

- **Compiled queries order by `reaction_id`.** The backend returns matches in no fixed
  order, so each page of results could reorder between visits. The dataset sample and
  the search form's queries add `order_by: [{key: 'reaction_id'}]`. Ranking a similarity
  search by score, as ord-interface did, is not in the grammar and is left out.
- **The provider's numeric ID is 0.** `ReactionProvider` types a dataset reaction's ID as
  a number, the editor's database ID. Nothing in the shared package reads it, so the
  viewer passes 0 and keys the provider by the reaction's ORD ID.
- **The charts draw their molecules on load.** Each chart renders its 30 molblocks in one
  `renderPreviews` call, cached by TanStack Query, so a hover shows the image at once.
- **`@mantine/charts` 7.17.8 and `recharts` ^2.15.4** join the viewer's dependencies.
  The charts package pins `@mantine/core` to its own version, which the lockfile already
  holds.
- **The fixture record is a generated TypeScript module.** The repository's TypeScript
  configuration does not enable JSON imports, so F4.1 writes
  `src/test/fixtures/records.ts` from the fixture corpus.
- **`routes.test.tsx` stubs `fetch`**, since `/` now fetches the datasets.
- **The end-to-end backend is `ord_viewer.testing:e2e_app`.** It reads the corpus from
  `ORD_VIEWER_CORPUS_DIR` and resolves names offline. Until F6 its ask client is None,
  so `/api/ask` answers 503; F6 gives it a scripted client.
- **The full record is protobuf JSON:** `toJson(ReactionSchema, …)` over the record's
  `binpb`, the reaction as ord-schema's JSON names it.

These came from executing F4–F6 (ord-app#896, #897, and #899); the design file has been
updated to match.

- **Helpers leave their components' files.** React Refresh wants a component's file to
  export only components, so `VIEWER_SLOTS` (`#reaction/slots.ts`), `ReactionLink`,
  `fullRecordJson`, and `selectedIds` each have a module of their own.
- **`renderAt` passes its providers as Testing Library's wrapper**, so a rerender keeps
  them, the cache, and the location, and it mounts `Notifications` for the failures
  that show as one.
- **An ID the corpus does not hold is named.** The backend skips such an ID, so
  `ReactionList` names the ones that did not come back, wherever it lists reactions.
- **Failures reach the reader.** A failed copy shows a notification holding the address;
  molecules that could not be drawn say so, with Retry. Copy link copies the address as
  it is when clicked, not as it was rendered.
- **No page scrolls sideways at 375 px.** Links in free text break anywhere, the
  datasets table scrolls inside its own container, the stacked search page stretches its
  results to the screen, and `/ask`'s examples wrap. `e2e/narrow.spec.ts` checks each
  page at that width with full-length IDs and links; #898 did the same for the shared
  reaction view.
- **The screenshots** capture the 1280×1080 viewport and mask the footer's year, as the
  editor's do, and their baselines came from CI's first run. Playwright's specs are not
  in `tsc -b`, as the editor's are not.
- **The coverage floors** are 99% for lines, statements, and functions and 100% for
  branches, in whole percentages. When F4's branches fell to 95.3%, the uncovered paths
  got tests, and the floor stayed.
- **The search form:**
  - a blank bound or value, such as `min_yield=` or `dataset_id=` in a URL, counts as
    missing, not as 0 or a clause that matches nothing;
  - structure rows keep stable keys, so removing one keeps the others' drawings;
  - "Match stereochemistry" is enabled only beside a substructure, a SMARTS, or a
    reaction SMARTS, the patterns it applies to, and the URL carries
    `use_stereochemistry` with a reaction SMARTS as well as with a structure;
  - hiding the form keeps its unsent edits, and the help note is plain text, since an
    alert would be announced on load and found in place of a search's error.
- **The results:**
  - View selected is a disabled button while nothing is selected;
  - a search that stops at its own limit says so, since `truncated` marks only the
    1,000-row bound, with the advice its page gives: raise the limit, or ask for more;
  - a table keys its rows and columns by their content, numbered among repeats.
- **The test corpus** gives `ord-viewer0202` a DOI and a 30% conversion, so the DOI and
  conversion searches have something to find, and `VIEWER0103` joins the fixture
  records.
- **`/ask`:**
  - the in-development note is plain text, for the help note's reason;
  - the question box is keyed by the URL's question, so Back shows that question;
  - the 2,000-character bound counts code points after trimming, as the backend does;
  - Ask asks a failed question again and leaves an answered one in the cache, so a 429
    or 503 can be retried without paying twice for an answer;
  - the scripted acetyl chloride query orders by `reaction_id`, and
    `ScriptedAskClient` reads each message's content as the string `nl.ask` sends.

---

## PR F4: browse, reactions, the selected set, and the end-to-end job

Branch `viewer-browse`, in its own worktree from `origin/main`
(`~/ord/worktrees/ord-app/viewer-browse`). Run `npm ci` in `frontend/` and
`uv sync --frozen` in `backend/viewer` first.

### Task F4.1: A record as a read-only reaction

**Files:**

- Create: `frontend/apps/viewer/scripts/fixture-records.py`,
  `frontend/apps/viewer/src/test/fixtures/records.ts` (generated),
  `frontend/apps/viewer/src/reaction/snapshot.ts`,
  `frontend/apps/viewer/src/reaction/snapshot.test.ts`,
  `frontend/apps/viewer/src/reaction/ViewerReactionProvider.tsx`,
  `frontend/apps/viewer/src/reaction/ViewerReactionProvider.test.tsx`
- Modify: `.jscpd.json`, `frontend/eslint.config.mjs` (the generated fixture)

**Interfaces:**

- Produces:
  - `recordToSnapshot(record: ReactionRecord): ReactionSnapshot`;
  - `VIEWER_SLOTS: ReactionSlots`;
  - `ViewerReactionProvider({record, children})`;
  - the fixtures `VIEWER0101` and `VIEWER0102: ReactionRecord`.

- [ ] **Step 1: The fixture records.** The reaction views need real records, whose
  `binpb` and molblocks are impractical to write by hand.
  `frontend/apps/viewer/scripts/fixture-records.py`:

  ```python
  """Print the viewer's fixture records as a TypeScript module.

  Run from backend/viewer, whose environment has ord_viewer:

      uv run python ../../frontend/apps/viewer/scripts/fixture-records.py \
          > ../../frontend/apps/viewer/src/test/fixtures/records.ts

  then format the module with Prettier. Each record is GET /api/reactions's answer for
  one of the fixture corpus's reactions.
  """

  import json
  import pathlib
  import tempfile

  from ord_viewer.testing import derive_corpus, make_client

  REACTION_IDS = ("ord-viewer0101", "ord-viewer0102")


  def main() -> None:
      """Derive the fixture corpus and print its records as exported constants."""
      with tempfile.TemporaryDirectory() as directory:
          root = pathlib.Path(directory)
          derive_corpus(root)
          with make_client(root) as client:
              params = [("id", reaction_id) for reaction_id in REACTION_IDS]
              response = client.get("/api/reactions", params=params)
              response.raise_for_status()
              records = response.json()
      print("// Written by scripts/fixture-records.py; regenerate rather than edit.")
      print("import type { ReactionRecord } from '#api/types.ts';")
      for record in records:
          name = record["reaction_id"].removeprefix("ord-").upper()
          print(f"\nexport const {name}: ReactionRecord = {json.dumps(record)};")


  if __name__ == "__main__":
      main()
  ```

  Generate the module and format it:

  ```bash
  cd backend/viewer
  mkdir -p ../../frontend/apps/viewer/src/test/fixtures
  uv run python ../../frontend/apps/viewer/scripts/fixture-records.py \
    > ../../frontend/apps/viewer/src/test/fixtures/records.ts
  cd ../../frontend && npx prettier --write apps/viewer/src/test/fixtures/records.ts
  ```

  Expected: the module exports `VIEWER0101` and `VIEWER0102`, each with a `binpb`
  string and molblocks for two reactants and one product. Add
  `'apps/viewer/src/test/fixtures/records.ts'` to the first ESLint block's `ignores`
  beside `schema.ts`, under the comment "Generated by `scripts/fixture-records.py`.",
  and `"**/test/fixtures/records.ts"` to `.jscpd.json`'s `ignore`. addlicense stamps the
  module's header when it is committed, and again after a regeneration.

- [ ] **Step 2: Write the failing tests.** `src/reaction/snapshot.test.ts`:

  ```ts
  import { describe, expect, it } from 'vitest';
  import { recordToSnapshot } from '#reaction/snapshot.ts';
  import { VIEWER0101 } from '#test/fixtures/records.ts';

  describe('recordToSnapshot', () => {
    it('decodes the reaction and names it by its ORD ID', () => {
      const snapshot = recordToSnapshot(VIEWER0101);
      expect(snapshot.pb_reaction_id).toBe('ord-viewer0101');
      expect(Object.keys(snapshot.data.inputs)).toEqual(['reactants']);
      expect(snapshot.data.inputs.reactants.components).toHaveLength(2);
      expect(snapshot.data.outcomes[0].products).toHaveLength(1);
    });

    it('keys each molblock by the component it draws', () => {
      const snapshot = recordToSnapshot(VIEWER0101);
      const ids = [
        ...snapshot.data.inputs.reactants.components.map(component => component.id),
        snapshot.data.outcomes[0].products[0].id,
      ];
      for (const id of ids) {
        expect(snapshot.previews[id]).toMatch(/M {2}END/);
      }
    });

    it('carries an empty summary and no validity, as a record has neither', () => {
      const snapshot = recordToSnapshot(VIEWER0101);
      expect(snapshot.summary).toEqual({ provenance: {}, summary: {}, conditions: '' });
      expect(snapshot.is_valid).toBeUndefined();
    });
  });
  ```

  `src/reaction/ViewerReactionProvider.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { ReactionHeader } from '@open-reaction-database/ui/reaction';
  import { renderAt } from '#test/render.tsx';
  import { VIEWER0101 } from '#test/fixtures/records.ts';
  import {
    VIEWER_SLOTS,
    ViewerReactionProvider,
  } from '#reaction/ViewerReactionProvider.tsx';

  describe('ViewerReactionProvider', () => {
    it('shows the record through the shared view', () => {
      const { getByRole } = renderAt(
        '/',
        <ViewerReactionProvider record={VIEWER0101}>
          <ReactionHeader />
        </ViewerReactionProvider>,
      );
      expect(getByRole('heading', { name: 'ord-viewer0101' })).toBeInTheDocument();
    });

    it('shows no validation badge, since a record carries no validity', () => {
      const { queryByText } = renderAt(
        '/',
        <ViewerReactionProvider record={VIEWER0101}>
          <ReactionHeader />
        </ViewerReactionProvider>,
      );
      expect(queryByText(/valid/i)).not.toBeInTheDocument();
    });

    it('links another reaction to its page, encoding its ID once', () => {
      const ReactionLink = VIEWER_SLOTS.ReactionLink!;
      const { getByRole } = renderAt('/', <ReactionLink pbReactionId="a/b" />);
      expect(getByRole('link', { name: 'a/b' })).toHaveAttribute('href', '/reactions/a%2Fb');
    });

    it('offers no drawing', () => {
      expect(VIEWER_SLOTS.MoleculeEditor).toBeUndefined();
    });
  });
  ```

- [ ] **Step 3: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/reaction
  ```

  Expected: FAIL, `Failed to resolve import "#reaction/snapshot.ts"`.

- [ ] **Step 4: Write the snapshot.** `src/reaction/snapshot.ts`:

  ```ts
  import type { ReactionSnapshot } from '@open-reaction-database/ui/reaction';
  import {
    getReactionPreviews,
    ordBinpbToReaction,
  } from '@open-reaction-database/ui/reaction/model';
  import type { ReactionRecord } from '#api/types.ts';

  // The viewer's API returns no summary. ReactionCard renders only when it has one, and
  // reads its contents only for the details the viewer leaves off.
  const EMPTY_SUMMARY = { provenance: {}, summary: {}, conditions: '' };

  /** The record as the shared view reads it: its reaction, molblocks, and ORD ID. */
  export function recordToSnapshot(record: ReactionRecord): ReactionSnapshot {
    const data = ordBinpbToReaction(record.binpb);
    return {
      data,
      previews: getReactionPreviews(data, record.molblocks),
      summary: EMPTY_SUMMARY,
      pb_reaction_id: record.reaction_id,
    };
  }
  ```

  `src/reaction/ViewerReactionProvider.tsx`:

  ```tsx
  import { Anchor } from '@mantine/core';
  import {
    createStaticReactionSource,
    DatasetReactionValueLabel,
    ReactionProvider,
    ReactionViewButton,
    type ReactionLinkProps,
    type ReactionSlots,
  } from '@open-reaction-database/ui/reaction';
  import { useMemo, type ReactNode } from 'react';
  import { Link } from 'wouter';
  import type { ReactionRecord } from '#api/types.ts';
  import { recordToSnapshot } from '#reaction/snapshot.ts';

  function ReactionLink({ pbReactionId }: Readonly<ReactionLinkProps>) {
    return (
      <Anchor
        component={Link}
        href={`/reactions/${encodeURIComponent(pbReactionId)}`}
      >
        {pbReactionId}
      </Anchor>
    );
  }

  /** The view's slots: read-only, each reaction ID a link to its page, and no drawing. */
  export const VIEWER_SLOTS: ReactionSlots = {
    ViewDeleteButtons: ReactionViewButton,
    ValueLabel: DatasetReactionValueLabel,
    ViewOnlyLabel: DatasetReactionValueLabel,
    ReactionLink,
  };

  interface ViewerReactionProviderProps {
    record: ReactionRecord;
    children: ReactNode;
  }

  /** Supplies one record, read-only, to the shared reaction view beneath. */
  export function ViewerReactionProvider({
    record,
    children,
  }: Readonly<ViewerReactionProviderProps>) {
    const source = useMemo(
      () => createStaticReactionSource(recordToSnapshot(record)),
      [record],
    );
    return (
      // The ID is the editor's database ID, which nothing in the shared view reads; the
      // key starts the drawer stack afresh for each reaction.
      <ReactionProvider
        key={record.reaction_id}
        reactionId={0}
        source={source}
        slots={VIEWER_SLOTS}
      >
        {children}
      </ReactionProvider>
    );
  }
  ```

- [ ] **Step 5: Run the tests to see them pass.** Same command as Step 3. Expected: 7
  passed. If `record.molblocks` does not type-check against `getReactionPreviews`'s
  `ReactionMolBlocks`, compare the two shapes before casting; F4's planning found them
  identical.

- [ ] **Step 6: Commit.**

  ```bash
  git add frontend/apps/viewer/scripts frontend/apps/viewer/src/test/fixtures \
    frontend/apps/viewer/src/reaction frontend/eslint.config.mjs .jscpd.json
  git commit -m "Show a viewer record through the shared, read-only reaction view"
  ```

### Task F4.2: Links in free text

**Files:**

- Create: `frontend/apps/viewer/src/components/LinkedText.tsx`,
  `frontend/apps/viewer/src/components/LinkedText.test.tsx`

**Interfaces:**

- Produces: `LinkedText({text})`, which links web addresses and bare DOIs in `text`, as
  ord-interface's `LinkedText` does for dataset descriptions.

- [ ] **Step 1: Write the failing tests.** `src/components/LinkedText.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { renderAt } from '#test/render.tsx';
  import { LinkedText } from '#components/LinkedText.tsx';

  function links(text: string) {
    const { queryAllByRole } = renderAt('/', <LinkedText text={text} />);
    return queryAllByRole('link').map(link => [
      link.textContent,
      link.getAttribute('href'),
    ]);
  }

  describe('LinkedText', () => {
    it.each([
      ['See https://example.com/a.', [['https://example.com/a', 'https://example.com/a']]],
      ['At www.example.com today', [['www.example.com', 'https://www.example.com']]],
      [
        'DOI: 10.1021/jacs.6c05959.',
        [['10.1021/jacs.6c05959', 'https://doi.org/10.1021/jacs.6c05959']],
      ],
      [
        '(DOI: 10.15227/orgsyn.095.0080)',
        [['10.15227/orgsyn.095.0080', 'https://doi.org/10.15227/orgsyn.095.0080']],
      ],
      [
        'https://en.wikipedia.org/wiki/Foo_(bar)',
        [
          [
            'https://en.wikipedia.org/wiki/Foo_(bar)',
            'https://en.wikipedia.org/wiki/Foo_(bar)',
          ],
        ],
      ],
      [
        'https://doi.org/10.1/x and 10.2/y',
        [
          ['https://doi.org/10.1/x', 'https://doi.org/10.1/x'],
          ['10.2/y', 'https://doi.org/10.2/y'],
        ],
      ],
      ['No links here', []],
    ])('links %j', (text, expected) => {
      expect(links(text)).toEqual(expected);
    });

    it('keeps the text around the links', () => {
      const { container } = renderAt(
        '/',
        <LinkedText text="Before https://example.com, after." />,
      );
      expect(container).toHaveTextContent('Before https://example.com, after.');
    });

    it('opens links in a new tab', () => {
      const { getByRole } = renderAt('/', <LinkedText text="https://example.com" />);
      expect(getByRole('link')).toHaveAttribute('target', '_blank');
      expect(getByRole('link')).toHaveAttribute('rel', 'noopener noreferrer');
    });
  });
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/components/LinkedText.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import "#components/LinkedText.tsx"`.

- [ ] **Step 3: Write the component.** `src/components/LinkedText.tsx`, ord-interface's
  rule in Mantine's `Anchor`:

  ```tsx
  import { Anchor } from '@mantine/core';
  import type { ReactNode } from 'react';

  // Web addresses, and bare DOIs ("10.1021/jacs.6c05959", with or without a "DOI:"
  // prefix). The address branch comes first, so the DOI in https://doi.org/10.1021/…
  // is part of the address rather than a match of its own.
  const LINK_PATTERN = /(?:https?:\/\/|www\.)[^\s<>"']+|\b10\.\d{4,9}\/[^\s<>"']+/g;
  const TRAILING_PUNCTUATION = /[.,;:!?'"]+$/;
  const OPENING_BRACKETS: Record<string, string> = { ')': '(', ']': '[', '}': '{' };

  function count(text: string, character: string): number {
    return text.split(character).length - 1;
  }

  // Punctuation ending a match usually belongs to the prose around it. A closing bracket
  // stays only when the link holds its opener: "(DOI: 10.1/x)" drops the parenthesis,
  // and ".../Foo_(bar)" keeps it.
  function trimTrailingPunctuation(link: string): string {
    let trimmed = link.replace(TRAILING_PUNCTUATION, '');
    for (;;) {
      const closing = trimmed.slice(-1);
      const opening = OPENING_BRACKETS[closing];
      if (!opening || count(trimmed, opening) >= count(trimmed, closing)) {
        return trimmed;
      }
      trimmed = trimmed.slice(0, -1).replace(TRAILING_PUNCTUATION, '');
    }
  }

  function hrefOf(link: string): string {
    if (/^https?:\/\//i.test(link)) {
      return link;
    }
    if (/^www\./i.test(link)) {
      return `https://${link}`;
    }
    return `https://doi.org/${link}`;
  }

  /** The text, with its web addresses and DOIs as links that open in a new tab. */
  export function LinkedText({ text }: Readonly<{ text: string }>) {
    const nodes: Array<ReactNode> = [];
    const pattern = new RegExp(LINK_PATTERN);
    let cursor = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      const link = trimTrailingPunctuation(match[0]);
      if (match.index > cursor) {
        nodes.push(text.slice(cursor, match.index));
      }
      nodes.push(
        <Anchor
          key={match.index}
          href={hrefOf(link)}
          target="_blank"
          rel="noopener noreferrer"
        >
          {link}
        </Anchor>,
      );
      cursor = match.index + link.length;
      // Resume after the link, so the punctuation it left out is text.
      pattern.lastIndex = cursor;
    }
    if (cursor < text.length) {
      nodes.push(text.slice(cursor));
    }
    return <>{nodes}</>;
  }
  ```

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: 9
  passed.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/components/LinkedText.tsx \
    frontend/apps/viewer/src/components/LinkedText.test.tsx
  git commit -m "Link web addresses and DOIs in the viewer's free text"
  ```

### Task F4.3: Lists, paging, downloads, and errors

**Files:**

- Create, under `frontend/apps/viewer/src/`: `test/fetch.ts`, `components/paging.tsx`,
  `components/paging.test.tsx`, `components/ErrorNotice.tsx`,
  `components/ErrorNotice.test.tsx`, `components/DownloadButton.tsx`,
  `components/DownloadButton.test.tsx`, `components/CopyLinkButton.tsx`,
  `components/CopyLinkButton.test.tsx`, `components/ReactionList.tsx`,
  `components/ReactionList.test.tsx`

**Interfaces:**

- Consumes: `useReactions`, `downloadReactions`, `errorMessage` (F2);
  `ViewerReactionProvider` (F4.1).
- Produces:
  - `mockApi(routes)` in `#test/fetch.ts`: a `fetch` spy answering from a table keyed
    `"<METHOD> <path>"`, or `"<METHOD> <path>?<query>"` for an exact query, with 404
    for anything else;
  - `PAGE_SIZES` and `usePaging(items, noun)` → `{pageItems, controls}`;
  - `ErrorNotice({error})`, `DownloadButton({reactionIds, children?})`,
    `CopyLinkButton()`;
  - `ReactionList({reactionIds})`, which lists the reactions ten to a page by default,
    fetching each page with one request.

- [ ] **Step 1: The fetch table.** `src/test/fetch.ts`, test-only:

  ```ts
  import { vi } from 'vitest';

  /** A route's answer: a JSON body, or a function returning a fresh Response. */
  export type MockAnswer = unknown;

  /**
   * Answers fetch from a table of routes, and records what was asked.
   *
   * A key is "<METHOD> <path>" or, to match one query string exactly,
   * "<METHOD> <path>?<query>"; an exact key wins. A function answer is called for each
   * request, since a Response's body can be read only once. Any other request answers
   * 404 with FastAPI's body.
   */
  export function mockApi(routes: Record<string, MockAnswer>) {
    return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = new URL(String(input), 'http://viewer.test');
      const method = init?.method ?? 'GET';
      const exact = `${method} ${url.pathname}${url.search}`;
      const loose = `${method} ${url.pathname}`;
      const answer = exact in routes ? routes[exact] : routes[loose];
      if (answer === undefined) {
        return new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 });
      }
      if (typeof answer === 'function') {
        return (answer as () => Response)();
      }
      return new Response(JSON.stringify(answer));
    });
  }
  ```

- [ ] **Step 2: Write the failing tests.** `src/components/paging.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { usePaging } from '#components/paging.tsx';

  const ITEMS = Array.from({ length: 23 }, (_, index) => `item ${index + 1}`);

  function Paged({ items }: Readonly<{ items: ReadonlyArray<string> }>) {
    const { pageItems, controls } = usePaging(items, 'items');
    return (
      <>
        {controls}
        <ul>
          {pageItems.map(item => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </>
    );
  }

  describe('usePaging', () => {
    it('shows ten to a page, and counts them all', () => {
      const { getAllByRole, getByText } = renderAt('/', <Paged items={ITEMS} />);
      expect(getAllByRole('listitem')).toHaveLength(10);
      expect(getByText('of 23 items')).toBeInTheDocument();
    });

    it('moves between pages', async () => {
      const user = userEvent.setup();
      const { getAllByRole, getByRole } = renderAt('/', <Paged items={ITEMS} />);
      await user.click(getByRole('button', { name: '3' }));
      expect(getAllByRole('listitem').map(item => item.textContent)).toEqual([
        'item 21',
        'item 22',
        'item 23',
      ]);
    });

    it('starts again from the first page at a new page size', async () => {
      const user = userEvent.setup();
      const { getAllByRole, getByRole } = renderAt('/', <Paged items={ITEMS} />);
      await user.click(getByRole('button', { name: '3' }));
      await user.selectOptions(getByRole('combobox', { name: 'Per page' }), '25');
      expect(getAllByRole('listitem')).toHaveLength(23);
      expect(getAllByRole('listitem')[0]).toHaveTextContent('item 1');
    });

    it('starts again from the first page for new items', async () => {
      const user = userEvent.setup();
      const { getAllByRole, getByRole, rerender } = renderAt('/', <Paged items={ITEMS} />);
      await user.click(getByRole('button', { name: '3' }));
      rerender(<Paged items={ITEMS.slice(0, 15)} />);
      expect(getAllByRole('listitem')[0]).toHaveTextContent('item 1');
    });
  });
  ```

  Note `rerender` here renders outside `renderAt`'s providers; if Mantine complains,
  wrap the rerendered element in the same `MantineProvider` by exporting a `wrap(ui)`
  from `#test/render.tsx` and using it in both calls. Record that as a ruling.

  `src/components/ErrorNotice.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { renderAt } from '#test/render.tsx';
  import { ApiError } from '#api/client.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';

  describe('ErrorNotice', () => {
    it("says what errorMessage says about the failure", () => {
      const { getByRole } = renderAt(
        '/',
        <ErrorNotice error={new ApiError(503, 'busy')} />,
      );
      expect(getByRole('alert')).toHaveTextContent(
        'The service is busy or unavailable; try again shortly.',
      );
    });

    it("explains nginx's own 502 while the backend starts", () => {
      const { getByRole } = renderAt(
        '/',
        <ErrorNotice error={new ApiError(502, 'Bad Gateway', false)} />,
      );
      expect(getByRole('alert')).toHaveTextContent('busy or unavailable');
    });
  });
  ```

  `src/components/DownloadButton.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { DownloadButton } from '#components/DownloadButton.tsx';
  import { downloadReactions } from '#api/download.ts';

  vi.mock('#api/download.ts', () => ({ downloadReactions: vi.fn() }));

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('DownloadButton', () => {
    it('downloads the reactions it is given', async () => {
      vi.mocked(downloadReactions).mockResolvedValue(undefined);
      const user = userEvent.setup();
      const { getByRole } = renderAt('/', <DownloadButton reactionIds={['ord-a', 'ord-b']} />);
      await user.click(getByRole('button', { name: 'Download' }));
      expect(downloadReactions).toHaveBeenCalledWith(['ord-a', 'ord-b']);
    });

    it('says why a download failed', async () => {
      vi.mocked(downloadReactions).mockRejectedValue(new TypeError('Failed to fetch'));
      const user = userEvent.setup();
      const { getByRole, findByText } = renderAt(
        '/',
        <DownloadButton reactionIds={['ord-a']} />,
      );
      await user.click(getByRole('button', { name: 'Download' }));
      expect(await findByText('The viewer could not reach its server.')).toBeInTheDocument();
    });

    it('is disabled with nothing to download', () => {
      const { getByRole } = renderAt('/', <DownloadButton reactionIds={[]} />);
      expect(getByRole('button', { name: 'Download' })).toBeDisabled();
    });
  });
  ```

  The failure's notification renders through `@mantine/notifications`; if `findByText`
  cannot see it, add `<Notifications />` to `renderAt`'s providers and record the
  ruling.

  `src/components/CopyLinkButton.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { CopyLinkButton } from '#components/CopyLinkButton.tsx';

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('CopyLinkButton', () => {
    it("copies the page's address, and says so", async () => {
      const user = userEvent.setup();
      const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
      const { getByRole, findByRole } = renderAt('/', <CopyLinkButton />);
      await user.click(getByRole('button', { name: 'Copy link' }));
      expect(writeText).toHaveBeenCalledWith(globalThis.location.href);
      expect(await findByRole('button', { name: 'Link copied' })).toBeInTheDocument();
    });
  });
  ```

  `src/components/ReactionList.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0101, VIEWER0102 } from '#test/fixtures/records.ts';
  import { ReactionList } from '#components/ReactionList.tsx';

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('ReactionList', () => {
    it('shows a card for each reaction, linking it and its dataset', async () => {
      mockApi({ 'GET /api/reactions': [VIEWER0101, VIEWER0102] });
      const { findByRole, getAllByRole, getByRole } = renderAt(
        '/',
        <ReactionList reactionIds={['ord-viewer0101', 'ord-viewer0102']} />,
      );
      expect(await findByRole('link', { name: 'ord-viewer0101' })).toHaveAttribute(
        'href',
        '/reactions/ord-viewer0101',
      );
      expect(getByRole('link', { name: 'ord-viewer0102' })).toBeInTheDocument();
      // Both reactions are in the first dataset, so each card links it.
      for (const link of getAllByRole('link', { name: 'ord_dataset-viewer01' })) {
        expect(link).toHaveAttribute('href', '/datasets/ord_dataset-viewer01');
      }
    });

    it('asks for one page of reactions at a time', async () => {
      const ids = Array.from({ length: 12 }, (_, index) => `ord-${index}`);
      const fetch = mockApi({ 'GET /api/reactions': [] });
      const user = userEvent.setup();
      const { getByRole } = renderAt('/', <ReactionList reactionIds={ids} />);
      await user.click(getByRole('button', { name: '2' }));
      const asked = fetch.mock.calls.map(([input]) =>
        new URL(String(input), 'http://viewer.test').searchParams.getAll('id'),
      );
      expect(asked).toEqual([ids.slice(0, 10), ids.slice(10)]);
    });

    it('says so when there is nothing to list', () => {
      const { getByText } = renderAt('/', <ReactionList reactionIds={[]} />);
      expect(getByText('No reactions.')).toBeInTheDocument();
    });

    it('says why a page could not load', async () => {
      mockApi({});
      const { findByRole } = renderAt('/', <ReactionList reactionIds={['ord-viewer0101']} />);
      expect(await findByRole('alert')).toHaveTextContent('Not found.');
    });
  });
  ```

  The second test counts requests per page: with the cache, revisiting page 1 asks
  nothing new, which a later reader may want; it is not asserted here.

- [ ] **Step 3: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/components
  ```

  Expected: FAIL, with `Failed to resolve import` for each new component.

- [ ] **Step 4: Write the components.** `src/components/paging.tsx`:

  ```tsx
  import { Group, NativeSelect, Pagination, Text } from '@mantine/core';
  import { useMemo, useState, type ReactNode } from 'react';

  /** The page sizes offered, as ord-interface's tables offer them. */
  export const PAGE_SIZES = [10, 25, 50, 100];

  /**
   * Splits items into pages, with controls for the page and its size.
   *
   * New items, or a new page size, start again from the first page. Callers keep the
   * same items array between renders (for example with useMemo), since a new array is
   * read as new items.
   */
  export function usePaging<T>(
    items: ReadonlyArray<T>,
    noun: string,
  ): { pageItems: ReadonlyArray<T>; controls: ReactNode } {
    const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
    const [page, setPage] = useState(1);
    const [pagedItems, setPagedItems] = useState(items);
    if (pagedItems !== items) {
      setPagedItems(items);
      setPage(1);
    }
    const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
    const current = Math.min(page, pageCount);
    const pageItems = useMemo(
      () => items.slice((current - 1) * pageSize, current * pageSize),
      [items, current, pageSize],
    );
    const controls = (
      <Group
        justify="space-between"
        wrap="wrap"
        gap="sm"
      >
        <Group gap="xs">
          <Text size="sm">Showing</Text>
          <NativeSelect
            aria-label="Per page"
            size="xs"
            data={PAGE_SIZES.map(String)}
            value={String(pageSize)}
            onChange={event => {
              setPageSize(Number(event.currentTarget.value));
              setPage(1);
            }}
          />
          <Text size="sm">
            of {items.length.toLocaleString()} {noun}
          </Text>
        </Group>
        <Pagination
          size="sm"
          total={pageCount}
          value={current}
          onChange={setPage}
        />
      </Group>
    );
    return { pageItems, controls };
  }
  ```

  `src/components/ErrorNotice.tsx`:

  ```tsx
  import { Alert } from '@mantine/core';
  import { errorMessage } from '#api/client.ts';

  /** What went wrong with a request, as errorMessage tells it. */
  export function ErrorNotice({ error }: Readonly<{ error: unknown }>) {
    return (
      <Alert
        color="red"
        variant="light"
        title="This could not be loaded"
      >
        {errorMessage(error)}
      </Alert>
    );
  }
  ```

  `src/components/DownloadButton.tsx`:

  ```tsx
  import { Button } from '@mantine/core';
  import {
    NotificationVariant,
    showNotification,
  } from '@open-reaction-database/ui/display';
  import { DownloadIcon } from '@open-reaction-database/ui/theme';
  import { useState, type ReactNode } from 'react';
  import { errorMessage } from '#api/client.ts';
  import { downloadReactions } from '#api/download.ts';

  interface DownloadButtonProps {
    /** At most 1,000, the backend's bound. */
    reactionIds: ReadonlyArray<string>;
    children?: ReactNode;
  }

  /** Saves the reactions as one gzipped ord.Dataset, or says why it could not. */
  export function DownloadButton({
    reactionIds,
    children = 'Download',
  }: Readonly<DownloadButtonProps>) {
    const [busy, setBusy] = useState(false);
    const download = async () => {
      setBusy(true);
      try {
        await downloadReactions(reactionIds);
      } catch (error) {
        showNotification({
          variant: NotificationVariant.ERROR,
          title: 'The download failed',
          message: errorMessage(error),
        });
      } finally {
        setBusy(false);
      }
    };
    return (
      <Button
        variant="default"
        leftSection={<DownloadIcon />}
        loading={busy}
        disabled={reactionIds.length === 0}
        onClick={() => void download()}
      >
        {children}
      </Button>
    );
  }
  ```

  `src/components/CopyLinkButton.tsx`:

  ```tsx
  import { Button, CopyButton } from '@mantine/core';

  /** Copies the page's address, which holds everything needed to show it again. */
  export function CopyLinkButton() {
    return (
      <CopyButton value={globalThis.location.href}>
        {({ copied, copy }) => (
          <Button
            variant="default"
            onClick={copy}
          >
            {copied ? 'Link copied' : 'Copy link'}
          </Button>
        )}
      </CopyButton>
    );
  }
  ```

  `src/components/ReactionList.tsx`:

  ```tsx
  import { Anchor, Flex, Loader, Stack, Text } from '@mantine/core';
  import { ReactionCard } from '@open-reaction-database/ui/reaction';
  import { Link } from 'wouter';
  import { useReactions } from '#api/hooks.ts';
  import type { ReactionRecord } from '#api/types.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { usePaging } from '#components/paging.tsx';
  import { ViewerReactionProvider } from '#reaction/ViewerReactionProvider.tsx';

  function CardTitle({ record }: Readonly<{ record: ReactionRecord }>) {
    return (
      <Stack gap={0}>
        <Anchor
          component={Link}
          href={`/reactions/${encodeURIComponent(record.reaction_id)}`}
          fw={600}
        >
          {record.reaction_id}
        </Anchor>
        {record.dataset_id && (
          <Text size="sm">
            in{' '}
            <Anchor
              component={Link}
              href={`/datasets/${encodeURIComponent(record.dataset_id)}`}
            >
              {record.dataset_id}
            </Anchor>
          </Text>
        )}
      </Stack>
    );
  }

  interface ReactionListProps {
    /** The reactions, in order; the same array between renders, at most 1,000. */
    reactionIds: ReadonlyArray<string>;
  }

  /**
   * The reactions as cards, a page at a time; each page is one request, since a page
   * holds at most 100, the backend's bound for one.
   */
  export function ReactionList({ reactionIds }: Readonly<ReactionListProps>) {
    const { pageItems, controls } = usePaging(reactionIds, 'reactions');
    const records = useReactions(pageItems);
    if (reactionIds.length === 0) {
      return <Text>No reactions.</Text>;
    }
    return (
      <Stack gap="md">
        {controls}
        {records.isError ? (
          <ErrorNotice error={records.error} />
        ) : records.isPending ? (
          <Flex justify="center">
            <Loader />
          </Flex>
        ) : (
          records.data.map(record => (
            <ViewerReactionProvider
              key={record.reaction_id}
              record={record}
            >
              <ReactionCard
                title={<CardTitle record={record} />}
                actions={null}
              />
            </ViewerReactionProvider>
          ))
        )}
      </Stack>
    );
  }
  ```

  `ReactionList` calls `usePaging` and `useReactions` before its early return, as hooks
  must run on every render.

- [ ] **Step 5: Run the tests to see them pass.** Same command as Step 3. Expected: every
  test in `src/components` passes.

- [ ] **Step 6: Commit.**

  ```bash
  git add frontend/apps/viewer/src/test/fetch.ts frontend/apps/viewer/src/components
  git commit -m "List reactions a page at a time, with downloads, links, and errors"
  ```

### Task F4.4: The datasets

**Files:**

- Create: `frontend/apps/viewer/src/datasets/filterDatasets.ts`,
  `frontend/apps/viewer/src/datasets/filterDatasets.test.ts`,
  `frontend/apps/viewer/src/pages/DatasetsPage.tsx`,
  `frontend/apps/viewer/src/pages/DatasetsPage.test.tsx`

**Interfaces:**

- Consumes: `useDatasets` (F2); `usePaging`, `ErrorNotice`, `LinkedText`, `mockApi`
  (F4.2, F4.3).
- Produces: `filterDatasets(datasets, filter)`; `DatasetsPage`, the route `/` in F4.7.

- [ ] **Step 1: Write the failing tests.** `src/datasets/filterDatasets.test.ts`:

  ```ts
  import { describe, expect, it } from 'vitest';
  import type { DatasetSummary } from '#api/types.ts';
  import { filterDatasets } from '#datasets/filterDatasets.ts';

  const DATASETS: Array<DatasetSummary> = [
    { dataset_id: 'ord_dataset-1', name: 'Suzuki couplings', description: 'Pd', reactions: 120 },
    { dataset_id: 'ord_dataset-2', name: 'Amide couplings', description: 'HATU', reactions: 7 },
  ];

  describe('filterDatasets', () => {
    it.each([
      ['', ['ord_dataset-1', 'ord_dataset-2']],
      ['  ', ['ord_dataset-1', 'ord_dataset-2']],
      ['suzuki', ['ord_dataset-1']],
      ['COUPLINGS', ['ord_dataset-1', 'ord_dataset-2']],
      ['amide hatu', ['ord_dataset-2']],
      ['amide pd', []],
      ['dataset-2', ['ord_dataset-2']],
      ['120', ['ord_dataset-1']],
    ])('keeps what matches %j', (filter, expected) => {
      expect(filterDatasets(DATASETS, filter).map(dataset => dataset.dataset_id)).toEqual(
        expected,
      );
    });

    it('returns the same array for an empty filter', () => {
      expect(filterDatasets(DATASETS, '')).toBe(DATASETS);
    });
  });
  ```

  `src/pages/DatasetsPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { within } from '@testing-library/react';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { DatasetsPage } from '#pages/DatasetsPage.tsx';

  const DATASETS = Array.from({ length: 12 }, (_, index) => ({
    dataset_id: `ord_dataset-${index}`,
    name: `dataset ${index}`,
    description: index === 0 ? 'See https://example.com for more.' : `description ${index}`,
    reactions: 1000 + index,
  }));

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function rows(table: HTMLElement) {
    return within(table).getAllByRole('row').slice(1);
  }

  describe('DatasetsPage', () => {
    it('lists the first page of datasets, each linked to its page', async () => {
      mockApi({ 'GET /api/datasets': DATASETS });
      const { findByRole } = renderAt('/', <DatasetsPage />);
      const table = await findByRole('table');
      expect(rows(table)).toHaveLength(10);
      expect(within(table).getByRole('link', { name: 'dataset 3' })).toHaveAttribute(
        'href',
        '/datasets/ord_dataset-3',
      );
      expect(within(table).getByText('1,003')).toBeInTheDocument();
    });

    it('filters as the user types', async () => {
      mockApi({ 'GET /api/datasets': DATASETS });
      const user = userEvent.setup();
      const { findByRole, getByRole } = renderAt('/', <DatasetsPage />);
      const table = await findByRole('table');
      await user.type(getByRole('textbox', { name: 'Filter' }), 'dataset 11');
      expect(rows(table)).toHaveLength(1);
    });

    it('links the addresses in a description, and shows it whole in a modal', async () => {
      mockApi({ 'GET /api/datasets': DATASETS });
      const user = userEvent.setup();
      const { findByRole, getAllByRole } = renderAt('/', <DatasetsPage />);
      const table = await findByRole('table');
      expect(within(table).getByRole('link', { name: 'https://example.com' })).toBeInTheDocument();
      await user.click(getAllByRole('button', { name: 'Show all of the description' })[0]);
      // The modal renders in a portal, outside the table but inside the document.
      expect(await findByRole('dialog', { name: 'dataset 0' })).toHaveTextContent(
        'See https://example.com for more.',
      );
    });

    it('says why the datasets could not load', async () => {
      mockApi({
        'GET /api/datasets': () => new Response('<html>Bad Gateway</html>', { status: 502 }),
      });
      const { findByRole } = renderAt('/', <DatasetsPage />);
      expect(await findByRole('alert')).toHaveTextContent('busy or unavailable');
    });
  });
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/datasets src/pages/DatasetsPage.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import "#datasets/filterDatasets.ts"` and
  `"#pages/DatasetsPage.tsx"`.

- [ ] **Step 3: Write the filter and the page.** `src/datasets/filterDatasets.ts`:

  ```ts
  import type { DatasetSummary } from '#api/types.ts';

  /**
   * The datasets matching every word of the filter, as ord-interface's table matched them.
   *
   * A word matches a dataset when any of its fields, the reaction count included, holds it,
   * ignoring case. An empty filter returns the datasets as given.
   */
  export function filterDatasets(
    datasets: ReadonlyArray<DatasetSummary>,
    filter: string,
  ): ReadonlyArray<DatasetSummary> {
    const words = filter
      .toLowerCase()
      .split(/\s+/)
      .filter(word => word !== '');
    if (words.length === 0) {
      return datasets;
    }
    return datasets.filter(dataset => {
      const fields = [
        dataset.dataset_id,
        dataset.name,
        dataset.description,
        String(dataset.reactions),
      ].map(field => field.toLowerCase());
      return words.every(word => fields.some(field => field.includes(word)));
    });
  }
  ```

  `src/pages/DatasetsPage.tsx`:

  ```tsx
  import {
    ActionIcon,
    Anchor,
    Code,
    Flex,
    Loader,
    Modal,
    Stack,
    Table,
    Text,
    TextInput,
    Title,
  } from '@mantine/core';
  import { useMemo, useState } from 'react';
  import { Link } from 'wouter';
  import { useDatasets } from '#api/hooks.ts';
  import type { DatasetSummary } from '#api/types.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { LinkedText } from '#components/LinkedText.tsx';
  import { usePaging } from '#components/paging.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';
  import { filterDatasets } from '#datasets/filterDatasets.ts';

  function datasetPath(datasetId: string): string {
    return `/datasets/${encodeURIComponent(datasetId)}`;
  }

  /** The description, clamped to two lines, with a button that shows it whole. */
  function Description({ dataset }: Readonly<{ dataset: DatasetSummary }>) {
    const [opened, setOpened] = useState(false);
    return (
      <Flex
        gap="xs"
        align="flex-start"
      >
        <Text
          size="sm"
          lineClamp={2}
        >
          <LinkedText text={dataset.description} />
        </Text>
        <ActionIcon
          variant="subtle"
          size="sm"
          aria-label="Show all of the description"
          onClick={() => setOpened(true)}
        >
          …
        </ActionIcon>
        <Modal
          opened={opened}
          onClose={() => setOpened(false)}
          title={dataset.name}
          size="lg"
        >
          <Stack gap="sm">
            <Code>{dataset.dataset_id}</Code>
            <Text size="sm">{dataset.reactions.toLocaleString()} reactions</Text>
            <Text>
              <LinkedText text={dataset.description} />
            </Text>
          </Stack>
        </Modal>
      </Flex>
    );
  }

  function DatasetTable({ datasets }: Readonly<{ datasets: ReadonlyArray<DatasetSummary> }>) {
    const [filter, setFilter] = useState('');
    const shown = useMemo(() => filterDatasets(datasets, filter), [datasets, filter]);
    const { pageItems, controls } = usePaging(shown, 'datasets');
    return (
      <Stack gap="md">
        <TextInput
          label="Filter"
          placeholder="Words in a name, description, or ID"
          value={filter}
          onChange={event => setFilter(event.currentTarget.value)}
        />
        {controls}
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Description</Table.Th>
              <Table.Th>Reactions</Table.Th>
              <Table.Th>ID</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pageItems.map(dataset => (
              <Table.Tr key={dataset.dataset_id}>
                <Table.Td>
                  <Anchor
                    component={Link}
                    href={datasetPath(dataset.dataset_id)}
                  >
                    {dataset.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <Description dataset={dataset} />
                </Table.Td>
                <Table.Td>{dataset.reactions.toLocaleString()}</Table.Td>
                <Table.Td>
                  <Code>{dataset.dataset_id}</Code>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    );
  }

  /** Every dataset in the corpus, filtered and paged in the browser. */
  export function DatasetsPage() {
    const datasets = useDatasets();
    return (
      <ViewerPage breadcrumbs={[{ title: 'Datasets', path: '/' }]}>
        <Stack gap="md">
          <Title order={2}>Datasets</Title>
          {datasets.isError ? (
            <ErrorNotice error={datasets.error} />
          ) : datasets.isPending ? (
            <Flex justify="center">
              <Loader />
            </Flex>
          ) : (
            <DatasetTable datasets={datasets.data} />
          )}
        </Stack>
      </ViewerPage>
    );
  }
  ```

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes. The modal's description holds a link too, so "links the addresses" looks
  inside the table, not the whole document.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/datasets frontend/apps/viewer/src/pages/DatasetsPage.tsx \
    frontend/apps/viewer/src/pages/DatasetsPage.test.tsx
  git commit -m "List the corpus's datasets, filtered and paged in the browser"
  ```

### Task F4.5: A dataset, its charts, and a sample of its reactions

**Files:**

- Create, under `frontend/apps/viewer/src/`: `components/CompoundChart.tsx`,
  `components/CompoundChart.test.tsx`, `pages/DatasetPage.tsx`,
  `pages/DatasetPage.test.tsx`
- Modify: `frontend/apps/viewer/package.json`, `frontend/package-lock.json`,
  `frontend/apps/viewer/src/index.scss`, `frontend/apps/viewer/src/api/client.ts`,
  `frontend/apps/viewer/src/api/client.test.ts`

**Interfaces:**

- Consumes: `useDataset`, `useCompounds`, `useSearch`, `ApiError` (F2); `ReactionList`,
  `DownloadButton`, `CopyLinkButton`, `ErrorNotice`, `LinkedText` (F4.2, F4.3).
- Produces:
  - `isNotFound(error: unknown): boolean` in `#api/client.ts`;
  - `CompoundChart({datasetId, side, title})` and `CompoundTooltip({smiles, count,
    image})`;
  - `DATASET_SAMPLE = 100`;
  - `DatasetPage({datasetId})`, given the decoded ID by the route in F4.7.

- [ ] **Step 1: The charts' dependencies.** Add `"@mantine/charts": "^7.17.8"` and
  `"recharts": "^2.15.4"` to `frontend/apps/viewer/package.json`'s `dependencies`, run
  `npm install --ignore-scripts` from `frontend/`, and add
  `@import '@mantine/charts/styles.css';` to `src/index.scss` after the core styles.
  Expected: the lockfile gains `@mantine/charts` 7.17.8, matching `@mantine/core`, and
  `recharts` 2.x.

- [ ] **Step 2: Write the failing tests.** In `src/api/client.test.ts`, add `isNotFound` to
  the import from `#api/client.ts`, and:

  ```ts
  describe('isNotFound', () => {
    it.each([
      [new ApiError(404, 'Not Found'), true],
      [new ApiError(422, 'x'), false],
      [new TypeError('Failed to fetch'), false],
      [null, false],
    ])('says whether %o is a 404', (error, expected) => {
      expect(isNotFound(error)).toBe(expected);
    });
  });
  ```

  `src/components/CompoundChart.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import type { ReactNode } from 'react';
  import { renderPreviews } from '@open-reaction-database/ui/reaction/previews';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { CompoundChart, CompoundTooltip } from '#components/CompoundChart.tsx';

  // recharts measures its container, which happy-dom gives no size; the test reads what
  // the chart is given instead.
  vi.mock('@mantine/charts', () => ({
    BarChart: ({ data }: { data: Array<{ smiles: string; count: number }> }): ReactNode => (
      <ol aria-label="bars">
        {data.map(point => (
          <li key={point.smiles}>{`${point.smiles} ${point.count}`}</li>
        ))}
      </ol>
    ),
  }));
  vi.mock('@open-reaction-database/ui/reaction/previews', () => ({ renderPreviews: vi.fn() }));

  const COMPOUNDS = [
    { smiles: 'CC(=O)Cl', molblock: 'acetyl chloride molblock', count: 2 },
    { smiles: 'CCN', molblock: null, count: 1 },
  ];

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('CompoundChart', () => {
    it("draws the side's compounds in the order counted", async () => {
      vi.mocked(renderPreviews).mockResolvedValue({});
      const fetch = mockApi({ 'GET /api/datasets/ord_dataset-1/compounds': COMPOUNDS });
      const { findAllByRole, getByRole } = renderAt(
        '/',
        <CompoundChart
          datasetId="ord_dataset-1"
          side="products"
          title="Most frequent products"
        />,
      );
      expect((await findAllByRole('listitem')).map(item => item.textContent)).toEqual([
        'CC(=O)Cl 2',
        'CCN 1',
      ]);
      expect(getByRole('heading', { name: 'Most frequent products' })).toBeInTheDocument();
      expect(String(fetch.mock.calls[0][0])).toBe(
        '/api/datasets/ord_dataset-1/compounds?side=products',
      );
    });

    it("renders every compound's molecule once, keyed by its place", async () => {
      vi.mocked(renderPreviews).mockResolvedValue({});
      mockApi({ 'GET /api/datasets/ord_dataset-1/compounds': COMPOUNDS });
      const { findAllByRole } = renderAt(
        '/',
        <CompoundChart
          datasetId="ord_dataset-1"
          side="inputs"
          title="Most frequent inputs"
        />,
      );
      await findAllByRole('listitem');
      expect(renderPreviews).toHaveBeenCalledWith(
        { 0: 'acetyl chloride molblock', 1: null },
        { size: 160 },
      );
    });

    it('says so when the dataset has no compounds on that side', async () => {
      mockApi({ 'GET /api/datasets/ord_dataset-1/compounds': [] });
      const { findByText, queryByRole } = renderAt(
        '/',
        <CompoundChart
          datasetId="ord_dataset-1"
          side="inputs"
          title="Most frequent inputs"
        />,
      );
      expect(await findByText('No compounds to count.')).toBeInTheDocument();
      expect(queryByRole('list', { name: 'bars' })).not.toBeInTheDocument();
    });

    it('says why the counts could not load', async () => {
      mockApi({
        'GET /api/datasets/ord_dataset-1/compounds': () =>
          new Response(JSON.stringify({ detail: 'busy' }), { status: 503 }),
      });
      const { findByRole } = renderAt(
        '/',
        <CompoundChart
          datasetId="ord_dataset-1"
          side="inputs"
          title="Most frequent inputs"
        />,
      );
      expect(await findByRole('alert')).toHaveTextContent('busy or unavailable');
    });
  });

  describe('CompoundTooltip', () => {
    it('shows the molecule, its SMILES, and its count', () => {
      const { getByRole, getByText } = renderAt(
        '/',
        <CompoundTooltip
          smiles="CCN"
          count={1234}
          image="c3Zn"
        />,
      );
      expect(getByRole('img', { name: 'CCN' })).toHaveAttribute(
        'src',
        'data:image/svg+xml;base64,c3Zn',
      );
      expect(getByText('CCN')).toBeInTheDocument();
      expect(getByText('1,234 occurrences')).toBeInTheDocument();
    });

    it('shows the SMILES alone when there is no image', () => {
      const { queryByRole, getByText } = renderAt(
        '/',
        <CompoundTooltip
          smiles="CCN"
          count={1}
          image={null}
        />,
      );
      expect(queryByRole('img')).not.toBeInTheDocument();
      expect(getByText('1 occurrence')).toBeInTheDocument();
    });
  });
  ```

  `src/pages/DatasetPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import type { ReactNode } from 'react';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0101, VIEWER0102 } from '#test/fixtures/records.ts';
  import { DatasetPage } from '#pages/DatasetPage.tsx';

  vi.mock('@mantine/charts', () => ({ BarChart: (): ReactNode => null }));
  vi.mock('@open-reaction-database/ui/reaction/previews', () => ({
    renderPreviews: vi.fn().mockResolvedValue({}),
  }));

  const DATASET = {
    dataset_id: 'ord_dataset-viewer01',
    name: 'viewer one',
    description: 'A Suzuki coupling and two acylations',
    reactions: 3,
  };

  function api(sample: Array<string>) {
    return mockApi({
      'GET /api/datasets/ord_dataset-viewer01': DATASET,
      'GET /api/datasets/ord_dataset-viewer01/compounds': [],
      'POST /api/search': { kind: 'reactions', reaction_ids: sample, truncated: false },
      'GET /api/reactions': [VIEWER0101, VIEWER0102],
    });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('DatasetPage', () => {
    it('shows the dataset, its charts, and its reactions', async () => {
      api(['ord-viewer0101', 'ord-viewer0102']);
      const { findByRole, getByRole, getByText } = renderAt(
        '/datasets/ord_dataset-viewer01',
        <DatasetPage datasetId="ord_dataset-viewer01" />,
      );
      expect(await findByRole('heading', { name: 'viewer one' })).toBeInTheDocument();
      expect(getByText('ord_dataset-viewer01')).toBeInTheDocument();
      expect(getByText('A Suzuki coupling and two acylations')).toBeInTheDocument();
      expect(getByRole('heading', { name: 'Most frequent inputs' })).toBeInTheDocument();
      expect(getByRole('heading', { name: 'Most frequent products' })).toBeInTheDocument();
      expect(await findByRole('link', { name: 'ord-viewer0102' })).toBeInTheDocument();
    });

    it("asks for up to 100 of the dataset's reactions, in ID order", async () => {
      const fetch = api(['ord-viewer0101']);
      const { findByRole } = renderAt(
        '/datasets/ord_dataset-viewer01',
        <DatasetPage datasetId="ord_dataset-viewer01" />,
      );
      await findByRole('heading', { name: /reactions/i, level: 3 });
      const search = fetch.mock.calls.find(([input]) => String(input) === '/api/search');
      expect(JSON.parse(String(search?.[1]?.body))).toEqual({
        query: {
          where: {
            op: 'eq',
            path: 'dataset_id',
            value: { literal: 'ord_dataset-viewer01' },
          },
          order_by: [{ key: 'reaction_id' }],
          limit: 100,
        },
      });
    });

    it.each([
      [['ord-viewer0101', 'ord-viewer0102'], '2 reactions from this dataset (a sample)'],
      [['ord-viewer0101', 'ord-viewer0102', 'ord-viewer0103'], 'Reactions in this dataset (3)'],
    ])('titles a sample of %j as %j', async (sample, title) => {
      api(sample);
      const { findByRole } = renderAt(
        '/datasets/ord_dataset-viewer01',
        <DatasetPage datasetId="ord_dataset-viewer01" />,
      );
      expect(await findByRole('heading', { name: title })).toBeInTheDocument();
    });

    it('shows NotFound for a dataset the corpus does not hold', async () => {
      mockApi({});
      const { findByRole } = renderAt(
        '/datasets/ord_dataset-nowhere',
        <DatasetPage datasetId="ord_dataset-nowhere" />,
      );
      expect(await findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    });

    it('says why the dataset could not load', async () => {
      mockApi({
        'GET /api/datasets/ord_dataset-viewer01': () =>
          new Response(JSON.stringify({ detail: 'busy' }), { status: 503 }),
      });
      const { findByRole } = renderAt(
        '/datasets/ord_dataset-viewer01',
        <DatasetPage datasetId="ord_dataset-viewer01" />,
      );
      expect(await findByRole('alert')).toHaveTextContent('busy or unavailable');
    });
  });
  ```

- [ ] **Step 3: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/api/client.test.ts \
    src/components/CompoundChart.test.tsx src/pages/DatasetPage.test.tsx
  ```

  Expected: FAIL, `isNotFound` is not exported, and `Failed to resolve import` for the
  chart and the page.

- [ ] **Step 4: Write `isNotFound`, the chart, and the page.** Append to
  `src/api/client.ts`:

  ```ts
  /** Whether the server said the thing asked for does not exist. */
  export function isNotFound(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404;
  }
  ```

  `src/components/CompoundChart.tsx`:

  ```tsx
  import { BarChart } from '@mantine/charts';
  import { Flex, Loader, Paper, Stack, Text, Title } from '@mantine/core';
  import { renderPreviews } from '@open-reaction-database/ui/reaction/previews';
  import { useQuery } from '@tanstack/react-query';
  import { useMemo } from 'react';
  import { useCompounds } from '#api/hooks.ts';
  import type { CompoundCount, CompoundSide } from '#api/types.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';

  const IMAGE_SIZE = 160;

  interface CompoundTooltipProps {
    smiles: string;
    count: number;
    /** The molecule as a base64 SVG; null or undefined when there is none yet. */
    image: string | null | undefined;
  }

  /** A bar's molecule, SMILES, and count. */
  export function CompoundTooltip({ smiles, count, image }: Readonly<CompoundTooltipProps>) {
    return (
      <Paper
        p="xs"
        shadow="md"
        withBorder
        maw={IMAGE_SIZE + 40}
      >
        {image && (
          <img
            src={`data:image/svg+xml;base64,${image}`}
            alt={smiles}
            width={IMAGE_SIZE}
            height={IMAGE_SIZE}
          />
        )}
        <Text
          size="xs"
          style={{ wordBreak: 'break-all' }}
        >
          {smiles}
        </Text>
        <Text size="xs">
          {count.toLocaleString()} {count === 1 ? 'occurrence' : 'occurrences'}
        </Text>
      </Paper>
    );
  }

  /** The compounds' molecules, rendered together once and keyed by their place. */
  function useImages(
    datasetId: string,
    side: CompoundSide,
    compounds: ReadonlyArray<CompoundCount> | undefined,
  ) {
    return useQuery({
      queryKey: ['compound-images', datasetId, side],
      queryFn: () =>
        renderPreviews(
          Object.fromEntries(
            (compounds ?? []).map((compound, index) => [String(index), compound.molblock]),
          ),
          { size: IMAGE_SIZE },
        ),
      enabled: compounds !== undefined && compounds.length > 0,
    });
  }

  interface CompoundChartProps {
    datasetId: string;
    side: CompoundSide;
    title: string;
  }

  /**
   * The dataset's 30 most frequent compounds on one side, as bars of their occurrences;
   * hovering a bar shows its molecule.
   */
  export function CompoundChart({ datasetId, side, title }: Readonly<CompoundChartProps>) {
    const compounds = useCompounds(datasetId, side);
    const images = useImages(datasetId, side, compounds.data);
    const data = useMemo(
      () =>
        (compounds.data ?? []).map((compound, index) => ({
          key: String(index),
          smiles: compound.smiles,
          count: compound.count,
        })),
      [compounds.data],
    );
    let body;
    if (compounds.isError) {
      body = <ErrorNotice error={compounds.error} />;
    } else if (compounds.isPending) {
      body = (
        <Flex justify="center">
          <Loader />
        </Flex>
      );
    } else if (data.length === 0) {
      body = <Text>No compounds to count.</Text>;
    } else {
      body = (
        <BarChart
          h={280}
          data={data}
          dataKey="smiles"
          series={[{ name: 'count', label: 'Occurrences', color: 'blue.6' }]}
          xAxisProps={{ tick: false }}
          tooltipProps={{
            content: ({ payload }) => {
              const point = payload?.[0]?.payload as (typeof data)[number] | undefined;
              return point ? (
                <CompoundTooltip
                  smiles={point.smiles}
                  count={point.count}
                  image={images.data?.[point.key]}
                />
              ) : null;
            },
          }}
        />
      );
    }
    return (
      <Stack gap="xs">
        <Title order={3}>{title}</Title>
        {body}
      </Stack>
    );
  }
  ```

  `src/pages/DatasetPage.tsx`:

  ```tsx
  import { Code, Flex, Group, Loader, SimpleGrid, Stack, Text, Title } from '@mantine/core';
  import type { UseQueryResult } from '@tanstack/react-query';
  import { useMemo } from 'react';
  import { isNotFound } from '#api/client.ts';
  import { useDataset, useSearch } from '#api/hooks.ts';
  import type { DatasetSummary, Query, SearchResult } from '#api/types.ts';
  import { CompoundChart } from '#components/CompoundChart.tsx';
  import { CopyLinkButton } from '#components/CopyLinkButton.tsx';
  import { DownloadButton } from '#components/DownloadButton.tsx';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { LinkedText } from '#components/LinkedText.tsx';
  import { ReactionList } from '#components/ReactionList.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';
  import { NotFoundPage } from '#pages/NotFoundPage.tsx';

  /** The most reactions a dataset's page shows: one request's worth. */
  export const DATASET_SAMPLE = 100;

  // One array for every empty answer, so a list paged over it keeps its page.
  const NO_IDS: ReadonlyArray<string> = [];

  interface SampleProps {
    dataset: DatasetSummary;
    sample: UseQueryResult<SearchResult>;
  }

  function Sample({ dataset, sample }: Readonly<SampleProps>) {
    if (sample.isError) {
      return <ErrorNotice error={sample.error} />;
    }
    if (sample.isPending) {
      return (
        <Flex justify="center">
          <Loader />
        </Flex>
      );
    }
    const ids = sample.data.kind === 'reactions' ? sample.data.reaction_ids : NO_IDS;
    const title =
      dataset.reactions > ids.length
        ? `${ids.length} reactions from this dataset (a sample)`
        : `Reactions in this dataset (${ids.length})`;
    return (
      <Stack gap="md">
        <Group
          justify="space-between"
          wrap="wrap"
        >
          <Title order={3}>{title}</Title>
          <Group gap="sm">
            <CopyLinkButton />
            <DownloadButton reactionIds={ids}>Download all</DownloadButton>
          </Group>
        </Group>
        <ReactionList reactionIds={ids} />
      </Stack>
    );
  }

  /** A dataset: what it is, what it is made of, and a sample of its reactions. */
  export function DatasetPage({ datasetId }: Readonly<{ datasetId: string }>) {
    const dataset = useDataset(datasetId);
    const query = useMemo(
      (): Query => ({
        where: { op: 'eq', path: 'dataset_id', value: { literal: datasetId } },
        order_by: [{ key: 'reaction_id' }],
        limit: DATASET_SAMPLE,
      }),
      [datasetId],
    );
    const sample = useSearch(dataset.isSuccess ? query : null);
    if (isNotFound(dataset.error)) {
      return <NotFoundPage />;
    }
    const breadcrumbs = [
      { title: 'Datasets', path: '/' },
      {
        title: dataset.data?.name ?? datasetId,
        path: `/datasets/${encodeURIComponent(datasetId)}`,
      },
    ];
    let body;
    if (dataset.isError) {
      body = <ErrorNotice error={dataset.error} />;
    } else if (dataset.isPending) {
      body = (
        <Flex justify="center">
          <Loader />
        </Flex>
      );
    } else {
      body = (
        <Stack gap="lg">
          <Stack gap="xs">
            <Title order={2}>{dataset.data.name}</Title>
            <Code>{dataset.data.dataset_id}</Code>
            <Text>
              <LinkedText text={dataset.data.description} />
            </Text>
            <Text size="sm">{dataset.data.reactions.toLocaleString()} reactions</Text>
          </Stack>
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <CompoundChart
              datasetId={datasetId}
              side="inputs"
              title="Most frequent inputs"
            />
            <CompoundChart
              datasetId={datasetId}
              side="products"
              title="Most frequent products"
            />
          </SimpleGrid>
          <Sample
            dataset={dataset.data}
            sample={sample}
          />
        </Stack>
      );
    }
    return <ViewerPage breadcrumbs={breadcrumbs}>{body}</ViewerPage>;
  }
  ```

- [ ] **Step 5: Run the tests to see them pass.** Same command as Step 3. Expected: every
  test passes. If `tooltipProps.content`'s parameter type rejects the destructuring,
  type it as recharts' `TooltipProps<number, string>`, imported as a type from
  `recharts`, which F4.5's Step 1 made a direct dependency.

- [ ] **Step 6: Commit.**

  ```bash
  git add frontend/apps/viewer/package.json frontend/package-lock.json \
    frontend/apps/viewer/src/index.scss frontend/apps/viewer/src/api/client.ts \
    frontend/apps/viewer/src/api/client.test.ts frontend/apps/viewer/src/components/CompoundChart.tsx \
    frontend/apps/viewer/src/components/CompoundChart.test.tsx \
    frontend/apps/viewer/src/pages/DatasetPage.tsx frontend/apps/viewer/src/pages/DatasetPage.test.tsx
  git commit -m "Show a dataset, the compounds it uses most, and a sample of its reactions"
  ```

### Task F4.6: A reaction

**Files:**

- Create, under `frontend/apps/viewer/src/`: `components/FullRecordButton.tsx`,
  `components/FullRecordButton.test.tsx`, `pages/ReactionPage.tsx`,
  `pages/ReactionPage.test.tsx`

**Interfaces:**

- Consumes: `useReaction`, `useDatasets`, `isNotFound` (F2, F4.5);
  `ViewerReactionProvider` (F4.1); `DownloadButton`, `ErrorNotice` (F4.3).
- Produces:
  - `fullRecordJson(record): string` and `FullRecordButton({record})`;
  - `ReactionPage({reactionId})`, given the decoded ID by the route in F4.7.

- [ ] **Step 1: Write the failing tests.** `src/components/FullRecordButton.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { VIEWER0101 } from '#test/fixtures/records.ts';
  import { FullRecordButton, fullRecordJson } from '#components/FullRecordButton.tsx';

  describe('fullRecordJson', () => {
    it("is the reaction in ord-schema's JSON", () => {
      const json = JSON.parse(fullRecordJson(VIEWER0101));
      expect(json.reactionId).toBe('ord-viewer0101');
      expect(json.inputs.reactants.components).toHaveLength(2);
    });
  });

  describe('FullRecordButton', () => {
    it('shows the record in a modal', async () => {
      const user = userEvent.setup();
      const { getByRole, findByRole } = renderAt('/', <FullRecordButton record={VIEWER0101} />);
      await user.click(getByRole('button', { name: 'Full record' }));
      expect(await findByRole('dialog')).toHaveTextContent('"reactionId": "ord-viewer0101"');
    });
  });
  ```

  `src/pages/ReactionPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0101 } from '#test/fixtures/records.ts';
  import { downloadReactions } from '#api/download.ts';
  import { ReactionPage } from '#pages/ReactionPage.tsx';

  vi.mock('#api/download.ts', () => ({ downloadReactions: vi.fn() }));

  const DATASETS = [
    {
      dataset_id: 'ord_dataset-viewer01',
      name: 'viewer one',
      description: 'x',
      reactions: 3,
    },
  ];

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function show() {
    mockApi({
      'GET /api/reactions/ord-viewer0101': VIEWER0101,
      'GET /api/datasets': DATASETS,
    });
    return renderAt('/reactions/ord-viewer0101', <ReactionPage reactionId="ord-viewer0101" />);
  }

  describe('ReactionPage', () => {
    it('shows the reaction, under its dataset', async () => {
      const { findByRole, getByRole } = show();
      expect(await findByRole('heading', { name: 'ord-viewer0101' })).toBeInTheDocument();
      expect(await findByRole('link', { name: 'viewer one' })).toHaveAttribute(
        'href',
        '/datasets/ord_dataset-viewer01',
      );
      expect(getByRole('radio', { name: 'Tabs' })).toBeChecked();
    });

    it('offers no way to edit it', async () => {
      const { findByRole, queryByRole } = show();
      await findByRole('heading', { name: 'ord-viewer0101' });
      expect(queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
      expect(queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();
    });

    it('downloads the reaction', async () => {
      vi.mocked(downloadReactions).mockResolvedValue(undefined);
      const user = userEvent.setup();
      const { findByRole } = show();
      await user.click(await findByRole('button', { name: 'Download' }));
      expect(downloadReactions).toHaveBeenCalledWith(['ord-viewer0101']);
    });

    it('shows NotFound for a reaction the corpus does not hold', async () => {
      mockApi({ 'GET /api/datasets': DATASETS });
      const { findByRole } = renderAt(
        '/reactions/ord-nowhere',
        <ReactionPage reactionId="ord-nowhere" />,
      );
      expect(await findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    });

    it('says why the reaction could not load', async () => {
      mockApi({
        'GET /api/reactions/ord-viewer0101': () =>
          new Response(JSON.stringify({ detail: 'busy' }), { status: 503 }),
      });
      const { findByRole } = renderAt(
        '/reactions/ord-viewer0101',
        <ReactionPage reactionId="ord-viewer0101" />,
      );
      expect(await findByRole('alert')).toHaveTextContent('busy or unavailable');
    });
  });
  ```

  `SegmentedControl` renders its options as radio inputs; if its accessible names differ
  in the installed Mantine, query them by label text instead.

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/components/FullRecordButton.test.tsx \
    src/pages/ReactionPage.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import` for both.

- [ ] **Step 3: Write the button and the page.** `src/components/FullRecordButton.tsx`:

  ```tsx
  import { fromBinary, toJson } from '@bufbuild/protobuf';
  import { base64Decode } from '@bufbuild/protobuf/wire';
  import { ReactionSchema } from '@buf/open-reaction-database_ord-schema.bufbuild_es/ord-schema/proto/reaction_pb';
  import { Button, Code, Modal } from '@mantine/core';
  import { useDisclosure } from '@mantine/hooks';
  import { useMemo } from 'react';
  import type { ReactionRecord } from '#api/types.ts';

  /** The record's reaction as ord-schema's protobuf JSON, indented. */
  export function fullRecordJson(record: ReactionRecord): string {
    const reaction = fromBinary(ReactionSchema, base64Decode(record.binpb));
    return JSON.stringify(toJson(ReactionSchema, reaction), null, 2);
  }

  /** Shows the whole reaction as JSON, as ord-interface's Full record did. */
  export function FullRecordButton({ record }: Readonly<{ record: ReactionRecord }>) {
    const [opened, { open, close }] = useDisclosure();
    // Decoded only when shown, since most visits never open it.
    const json = useMemo(() => (opened ? fullRecordJson(record) : ''), [opened, record]);
    return (
      <>
        <Button
          variant="default"
          onClick={open}
        >
          Full record
        </Button>
        <Modal
          opened={opened}
          onClose={close}
          title={record.reaction_id}
          size="xl"
        >
          <Code block>{json}</Code>
        </Modal>
      </>
    );
  }
  ```

  `src/pages/ReactionPage.tsx`:

  ```tsx
  import {
    Flex,
    Loader,
    Paper,
    SegmentedControl,
    Stack,
    type SegmentedControlItem,
  } from '@mantine/core';
  import {
    ReactionContent,
    ReactionDetailsSidebar,
    ReactionHeader,
  } from '@open-reaction-database/ui/reaction';
  import type { Breadcrumbs } from '@open-reaction-database/ui/shell';
  import { useState } from 'react';
  import { isNotFound } from '#api/client.ts';
  import { useDatasets, useReaction } from '#api/hooks.ts';
  import type { ReactionRecord } from '#api/types.ts';
  import { DownloadButton } from '#components/DownloadButton.tsx';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { FullRecordButton } from '#components/FullRecordButton.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';
  import { NotFoundPage } from '#pages/NotFoundPage.tsx';
  import { ViewerReactionProvider } from '#reaction/ViewerReactionProvider.tsx';

  type ViewMode = 'tabs' | 'list';

  const VIEW_MODES: Array<SegmentedControlItem> = [
    { label: 'Tabs', value: 'tabs' },
    { label: 'List', value: 'list' },
  ];

  function reactionPath(reactionId: string): string {
    return `/reactions/${encodeURIComponent(reactionId)}`;
  }

  /** Datasets, then the reaction's dataset by name once the list has loaded, then it. */
  function useBreadcrumbs(reactionId: string, datasetId: string | null): Breadcrumbs {
    const datasets = useDatasets();
    const crumbs: Breadcrumbs = [{ title: 'Datasets', path: '/' }];
    if (datasetId !== null) {
      const name = datasets.data?.find(dataset => dataset.dataset_id === datasetId)?.name;
      crumbs.push({
        title: name ?? datasetId,
        path: `/datasets/${encodeURIComponent(datasetId)}`,
      });
    }
    crumbs.push({ title: reactionId, path: reactionPath(reactionId) });
    return crumbs;
  }

  function ReactionView({ record }: Readonly<{ record: ReactionRecord }>) {
    const [viewMode, setViewMode] = useState<ViewMode>('tabs');
    const breadcrumbs = useBreadcrumbs(record.reaction_id, record.dataset_id);
    return (
      <ViewerPage breadcrumbs={breadcrumbs}>
        <ViewerReactionProvider record={record}>
          <Stack gap="sm">
            <ReactionHeader
              actions={
                <>
                  <DownloadButton reactionIds={[record.reaction_id]} />
                  <FullRecordButton record={record} />
                </>
              }
            />
            <Paper p="xs">
              <SegmentedControl
                value={viewMode}
                onChange={value => setViewMode(value as ViewMode)}
                data={VIEW_MODES}
              />
            </Paper>
            <Paper
              radius="md"
              p="lg"
            >
              <ReactionContent viewMode={viewMode} />
            </Paper>
            <ReactionDetailsSidebar />
          </Stack>
        </ViewerReactionProvider>
      </ViewerPage>
    );
  }

  /** One reaction, read-only, as the editor's reaction page shows it. */
  export function ReactionPage({ reactionId }: Readonly<{ reactionId: string }>) {
    const reaction = useReaction(reactionId);
    if (isNotFound(reaction.error)) {
      return <NotFoundPage />;
    }
    if (reaction.isSuccess) {
      return <ReactionView record={reaction.data} />;
    }
    const breadcrumbs = [
      { title: 'Datasets', path: '/' },
      { title: reactionId, path: reactionPath(reactionId) },
    ];
    return (
      <ViewerPage breadcrumbs={breadcrumbs}>
        {reaction.isError ? (
          <ErrorNotice error={reaction.error} />
        ) : (
          <Flex justify="center">
            <Loader size="xl" />
          </Flex>
        )}
      </ViewerPage>
    );
  }
  ```

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/components/FullRecordButton.tsx \
    frontend/apps/viewer/src/components/FullRecordButton.test.tsx \
    frontend/apps/viewer/src/pages/ReactionPage.tsx frontend/apps/viewer/src/pages/ReactionPage.test.tsx
  git commit -m "Show a reaction read-only, with its download and full record"
  ```

### Task F4.7: The selected set, and the routes

**Files:**

- Create: `frontend/apps/viewer/src/pages/ReactionSetPage.tsx`,
  `frontend/apps/viewer/src/pages/ReactionSetPage.test.tsx`
- Modify: `frontend/apps/viewer/src/routes.tsx`, `frontend/apps/viewer/src/routes.test.tsx`

**Interfaces:**

- Consumes: `REACTIONS_PER_REQUEST` (F2); `routeParam` (F2); every page above.
- Produces:
  - `selectedIds(params: URLSearchParams): {ids, dropped}`;
  - `ReactionSetPage`;
  - the routes `/`, `/datasets/:datasetId`, `/reactions/:reactionId`, and `/reactions`.

- [ ] **Step 1: Write the failing tests.** `src/pages/ReactionSetPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0101, VIEWER0102 } from '#test/fixtures/records.ts';
  import { ReactionSetPage, selectedIds } from '#pages/ReactionSetPage.tsx';

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('selectedIds', () => {
    it('keeps the IDs in the order first given, once each', () => {
      expect(selectedIds(new URLSearchParams('id=b&id=a&id=b&id='))).toEqual({
        ids: ['b', 'a'],
        dropped: 0,
      });
    });

    it('keeps the first 100, and counts the rest', () => {
      const params = new URLSearchParams(
        Array.from({ length: 120 }, (_, index) => ['id', `ord-${index}`]),
      );
      const { ids, dropped } = selectedIds(params);
      expect(ids).toHaveLength(100);
      expect(ids[99]).toBe('ord-99');
      expect(dropped).toBe(20);
    });
  });

  describe('ReactionSetPage', () => {
    it('shows the selected reactions', async () => {
      mockApi({ 'GET /api/reactions': [VIEWER0102, VIEWER0101] });
      const { findByRole, getByRole } = renderAt(
        '/reactions?id=ord-viewer0102&id=ord-viewer0101',
        <ReactionSetPage />,
      );
      expect(await findByRole('link', { name: 'ord-viewer0102' })).toBeInTheDocument();
      expect(getByRole('heading', { name: 'Selected reactions' })).toBeInTheDocument();
      expect(getByRole('button', { name: 'Download all' })).toBeEnabled();
    });

    it('says how many past 100 it left out', async () => {
      mockApi({ 'GET /api/reactions': [] });
      const ids = Array.from({ length: 103 }, (_, index) => `id=ord-${index}`).join('&');
      const { findByText } = renderAt(`/reactions?${ids}`, <ReactionSetPage />);
      expect(
        await findByText('A set holds at most 100 reactions; the other 3 are left out.'),
      ).toBeInTheDocument();
    });

    it('says so when nothing is selected', () => {
      const { getByText } = renderAt('/reactions', <ReactionSetPage />);
      expect(getByText('No reactions.')).toBeInTheDocument();
    });
  });
  ```

  In `src/routes.test.tsx`, add `afterEach`, `beforeEach`, and `vi` to the vitest import,
  and import `mockApi` from `#test/fetch.ts` and `VIEWER0101` from
  `#test/fixtures/records.ts`. Then add, inside `describe('ViewerRoutes', …)`:

  ```tsx
  // The pages behind the redirects fetch as they render; an empty corpus answers them.
  beforeEach(() => {
    mockApi({
      'GET /api/datasets': [],
      'GET /api/reactions': [],
      'GET /api/reactions/ord-viewer0101': VIEWER0101,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows the datasets at /', async () => {
    const { findByRole } = renderAt('/', <ViewerRoutes />);
    expect(await findByRole('heading', { name: 'Datasets' })).toBeInTheDocument();
  });

  it('shows a reaction at /reactions/:id', async () => {
    const { findByRole } = renderAt('/reactions/ord-viewer0101', <ViewerRoutes />);
    expect(await findByRole('heading', { name: 'ord-viewer0101' })).toBeInTheDocument();
  });

  it('shows the selected set at /reactions', () => {
    const { getByRole } = renderAt('/reactions?id=ord-viewer0101', <ViewerRoutes />);
    expect(getByRole('heading', { name: 'Selected reactions' })).toBeInTheDocument();
  });

  it('asks for a dataset whose ID holds an escaped character by its whole ID', async () => {
    const fetch = vi.mocked(globalThis.fetch);
    renderAt('/datasets/a%2Fb', <ViewerRoutes />);
    await vi.waitFor(() =>
      expect(fetch.mock.calls.map(([input]) => String(input))).toContain(
        '/api/datasets/a%2Fb',
      ),
    );
  });
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/pages/ReactionSetPage.test.tsx src/routes.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import "#pages/ReactionSetPage.tsx"`, and the new
  route tests fail because `/` and the rest show NotFound.

- [ ] **Step 3: Write the page and the routes.** `src/pages/ReactionSetPage.tsx`:

  ```tsx
  import { Alert, Group, Stack, Title } from '@mantine/core';
  import { useMemo } from 'react';
  import { useSearchParams } from 'wouter';
  import { REACTIONS_PER_REQUEST } from '#api/hooks.ts';
  import { CopyLinkButton } from '#components/CopyLinkButton.tsx';
  import { DownloadButton } from '#components/DownloadButton.tsx';
  import { ReactionList } from '#components/ReactionList.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';

  /**
   * The set's reactions from the URL's id parameters: once each, in the order first
   * given, and at most one request's worth, with the count of those past it.
   */
  export function selectedIds(params: URLSearchParams): {
    ids: ReadonlyArray<string>;
    dropped: number;
  } {
    const unique = [...new Set(params.getAll('id').filter(id => id !== ''))];
    return {
      ids: unique.slice(0, REACTIONS_PER_REQUEST),
      dropped: Math.max(0, unique.length - REACTIONS_PER_REQUEST),
    };
  }

  /** Reactions chosen by ID, as a search's selection or a shared link names them. */
  export function ReactionSetPage() {
    const [searchParams] = useSearchParams();
    const search = searchParams.toString();
    const { ids, dropped } = useMemo(
      () => selectedIds(new URLSearchParams(search)),
      [search],
    );
    const path = search ? `/reactions?${search}` : '/reactions';
    return (
      <ViewerPage breadcrumbs={[{ title: 'Selected reactions', path }]}>
        <Stack gap="md">
          <Group
            justify="space-between"
            wrap="wrap"
          >
            <Title order={2}>Selected reactions</Title>
            <Group gap="sm">
              <CopyLinkButton />
              <DownloadButton reactionIds={ids}>Download all</DownloadButton>
            </Group>
          </Group>
          {dropped > 0 && (
            <Alert
              color="yellow"
              variant="light"
            >
              A set holds at most 100 reactions; the other {dropped} are left out.
            </Alert>
          )}
          <ReactionList reactionIds={ids} />
        </Stack>
      </ViewerPage>
    );
  }
  ```

  In `src/routes.tsx`, import the four pages, and add these routes at the top of the
  `Switch`, before `/about`:

  ```tsx
  <Route
    path="/"
    component={DatasetsPage}
  />
  <Route path="/datasets/:datasetId">
    {({ datasetId }) => <DatasetPage datasetId={routeParam(datasetId)} />}
  </Route>
  <Route path="/reactions/:reactionId">
    {({ reactionId }) => <ReactionPage reactionId={routeParam(reactionId)} />}
  </Route>
  <Route
    path="/reactions"
    component={ReactionSetPage}
  />
  ```

  wouter's routes match whole paths, so `/reactions` does not take `/reactions/:id`.

- [ ] **Step 4: Run the whole suite.**

  ```bash
  cd frontend/apps/viewer && npx vitest run 2>&1 | tail -4
  ```

  Expected: every test passes. The redirects' `history` tests still hold, since each
  redirect replaces the path before the page it lands on fetches.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/pages/ReactionSetPage.tsx \
    frontend/apps/viewer/src/pages/ReactionSetPage.test.tsx \
    frontend/apps/viewer/src/routes.tsx frontend/apps/viewer/src/routes.test.tsx
  git commit -m "Show a selected set of reactions, and route to every browse page"
  ```

### Task F4.8: End-to-end tests against the real backend

**Files:**

- Modify: `backend/viewer/ord_viewer/testing.py`, `backend/viewer/ord_viewer/testing_test.py`,
  `frontend/apps/viewer/package.json`, `frontend/package-lock.json`,
  `.github/workflows/tests.yml`
- Create: `frontend/apps/viewer/playwright.config.ts`, and under
  `frontend/apps/viewer/e2e/`: `browse.spec.ts`, `reaction.spec.ts`, `set.spec.ts`,
  `screenshots.spec.ts`

**Interfaces:**

- Produces:
  - `ord_viewer.testing.e2e_app() -> FastAPI`, for `uvicorn --factory`;
  - `npm run test:e2e -w apps/viewer`, against the viewer at `http://127.0.0.1:4174`;
  - the `test_e2e_viewer` job.

- [ ] **Step 1: Write the failing backend test.** Append to
  `backend/viewer/ord_viewer/testing_test.py`, and import `TestClient` from
  `fastapi.testclient` and `derive_corpus`, `e2e_app` from `ord_viewer.testing`:

  ```python
  def _inputs_holding(compound: str) -> dict:
      return {
          "query": {
              "where": {
                  "op": "exists",
                  "path": "inputs.components",
                  "where": {"op": "same_compound", "path": "smiles", "compound": compound},
              }
          }
      }


  def test_e2e_app_serves_the_environments_corpus(tmp_path, monkeypatch):
      derive_corpus(tmp_path)
      monkeypatch.setenv("ORD_VIEWER_CORPUS_DIR", str(tmp_path))
      with TestClient(e2e_app()) as client:
          assert client.get("/api/reactions/ord-viewer0101").status_code == 200


  def test_e2e_app_resolves_names_offline(tmp_path, monkeypatch):
      derive_corpus(tmp_path)
      monkeypatch.setenv("ORD_VIEWER_CORPUS_DIR", str(tmp_path))
      with TestClient(e2e_app()) as client:
          assert client.post("/api/search", json=_inputs_holding("pyridine")).status_code == 200
          unknown = client.post("/api/search", json=_inputs_holding("benzene"))
          assert unknown.status_code == 422
          assert "benzene" in unknown.json()["detail"]


  def test_e2e_app_has_no_model_client(tmp_path, monkeypatch):
      derive_corpus(tmp_path)
      monkeypatch.setenv("ORD_VIEWER_CORPUS_DIR", str(tmp_path))
      with TestClient(e2e_app()) as client:
          assert client.post("/api/ask", json={"question": "pyridine"}).status_code == 503
  ```

  Run `uv run pytest ord_viewer/testing_test.py -q` from `backend/viewer`. Expected:
  FAIL, `ImportError: cannot import name 'e2e_app'`.

- [ ] **Step 2: Write `e2e_app`.** `ord_viewer/testing.py` imports `FastAPI` and
  `create_app` already; add:

  ```python
  def e2e_app() -> FastAPI:
      """Build the app the viewer's end-to-end tests run against.

      Reads ORD_VIEWER_CORPUS_DIR and the other settings from the environment, as the
      image does, and resolves compound names from COMPOUND_NAMES, without the network.
      It has no model client, so /api/ask answers 503.

      Returns:
          The app, for ``uvicorn --factory ord_viewer.testing:e2e_app``.
      """
      return create_app(resolver=offline_resolver, ask_client_factory=lambda: None)
  ```

  Run the tests again. Expected: every test in `testing_test.py` passes.

- [ ] **Step 3: Playwright.** Add `"@playwright/test": "^1.60.0"` to the viewer's
  `devDependencies` and `"test:e2e": "playwright test"` to its scripts, and run
  `npm install --ignore-scripts` from `frontend/`. `frontend/apps/viewer/playwright.config.ts`:

  ```ts
  import { defineConfig, devices } from '@playwright/test';

  // The production build served by `vite preview`, which sends /api to the backend on
  // 8001. The caller starts both: the test_e2e_viewer job, or the README's commands.
  const BASE_URL = 'http://127.0.0.1:4174';

  export default defineConfig({
    testDir: './e2e',
    fullyParallel: true,
    forbidOnly: true,
    retries: 1,
    reporter: 'list',
    use: {
      baseURL: BASE_URL,
      trace: 'on-first-retry',
      // --disable-dev-shm-usage avoids renderer crashes on WASM-heavy pages (Indigo) in
      // CI containers with a small /dev/shm; --no-sandbox is required on CI runners.
      launchOptions: { args: ['--no-sandbox', '--disable-dev-shm-usage'] },
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  });
  ```

- [ ] **Step 4: The specs.** `e2e/browse.spec.ts`:

  ```ts
  import { readFile } from 'node:fs/promises';
  import { expect, test } from '@playwright/test';

  test('browses from the datasets to a dataset and its reactions', async ({ page }) => {
    await page.goto('/');
    const filter = page.getByRole('textbox', { name: 'Filter' });
    await expect(page.getByRole('link', { name: 'viewer one' })).toBeVisible();
    await filter.fill('two');
    await expect(page.getByRole('link', { name: 'viewer one' })).toHaveCount(0);
    await filter.fill('');
    await page.getByRole('link', { name: 'viewer one' }).click();
    await expect(page).toHaveURL('/datasets/ord_dataset-viewer01');
    await expect(page.getByRole('heading', { name: 'viewer one' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Reactions in this dataset (3)' })).toBeVisible();
    for (const id of ['ord-viewer0101', 'ord-viewer0102', 'ord-viewer0103']) {
      await expect(page.getByRole('link', { name: id, exact: true })).toBeVisible();
    }
  });

  test("draws a compound's molecule when its bar is hovered", async ({ page }) => {
    await page.goto('/datasets/ord_dataset-viewer01');
    await page.locator('.recharts-bar-rectangle').first().hover();
    await expect(
      page.locator('.recharts-tooltip-wrapper img[src^="data:image/svg+xml"]'),
    ).toBeVisible();
  });

  test("downloads a dataset's reactions as gzip", async ({ page }) => {
    await page.goto('/datasets/ord_dataset-viewer01');
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download all' }).click();
    const download = await downloading;
    expect(download.suggestedFilename()).toBe('ord-search-results.pb.gz');
    const bytes = await readFile(await download.path());
    expect([...bytes.subarray(0, 2)]).toEqual([0x1f, 0x8b]);
  });
  ```

  `e2e/reaction.spec.ts`:

  ```ts
  import { expect, test } from '@playwright/test';

  const PREVIEW = 'img[src^="data:image/svg+xml"]';

  test('shows a reaction read-only, with its drawer', async ({ page }) => {
    await page.goto('/reactions/ord-viewer0101');
    await expect(page.getByRole('heading', { name: 'ord-viewer0101' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'viewer one' })).toBeVisible();
    await expect(page.locator(PREVIEW).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Remove', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'View', exact: true }).first().click();
    const drawer = page.getByRole('dialog');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0);
  });

  test('shows the full record', async ({ page }) => {
    await page.goto('/reactions/ord-viewer0101');
    await page.getByRole('button', { name: 'Full record' }).click();
    await expect(page.getByRole('dialog')).toContainText('"reactionId": "ord-viewer0101"');
  });

  test('shows NotFound for an unknown reaction', async ({ page }) => {
    await page.goto('/reactions/ord-nowhere');
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  });
  ```

  `e2e/set.spec.ts`:

  ```ts
  import { expect, test } from '@playwright/test';

  const REACTION_LINK = /^ord-viewer\d{4}$/;

  test('shows a selected set in the order given', async ({ page }) => {
    await page.goto('/reactions?id=ord-viewer0103&id=ord-viewer0101');
    const links = page.getByRole('link', { name: REACTION_LINK });
    await expect(links).toHaveText(['ord-viewer0103', 'ord-viewer0101']);
  });

  test("redirects ord-interface's paths", async ({ page }) => {
    await page.goto('/selected-set?reaction_id=ord-viewer0102');
    await expect(page).toHaveURL('/reactions?id=ord-viewer0102');
    await page.goto('/id/ord-viewer0102');
    await expect(page).toHaveURL('/reactions/ord-viewer0102');
    await expect(page.getByRole('heading', { name: 'ord-viewer0102' })).toBeVisible();
  });

  test('shows NotFound for an unknown path', async ({ page }) => {
    await page.goto('/nowhere');
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  });
  ```

  `e2e/screenshots.spec.ts`, compared only in CI, as the editor's are:

  ```ts
  import { expect, test, type Page } from '@playwright/test';

  const PREVIEW = 'img[src^="data:image/svg+xml"]';
  const LOADER = '.mantine-Loader-root';

  test.describe.configure({ retries: 0 });
  test.use({ viewport: { width: 1280, height: 1080 } });

  async function settle(page: Page, previews: number) {
    await expect(page.locator(LOADER)).toHaveCount(0);
    await expect(page.locator(PREVIEW).filter({ visible: true })).toHaveCount(previews);
  }

  test.beforeEach(() => {
    // The baselines are rendered on CI's Linux runner; fonts and antialiasing differ
    // elsewhere, so a local comparison would fail on rendering alone.
    test.skip(!process.env.CI, 'Screenshots are compared only in CI, where the baselines are made.');
  });

  test('the reaction page looks the same', async ({ page }) => {
    await page.goto('/reactions/ord-viewer0101');
    // Three molecules in the header's preview, and two reactants in the inputs.
    await settle(page, 5);
    await expect(page).toHaveScreenshot('reaction-page.png', { fullPage: true });
  });

  test('a dataset page looks the same', async ({ page }) => {
    await page.goto('/datasets/ord_dataset-viewer01');
    // Three reactions' previews of three molecules each.
    await settle(page, 9);
    await expect(page).toHaveScreenshot('dataset-page.png', { fullPage: true });
  });
  ```

  The preview counts come from the fixture; if the first CI run shows a different count,
  read the page's screenshot in the report and set the count to what it shows, then
  record the ruling.

- [ ] **Step 5: Run them locally.** From the worktree's root, in three terminals or with
  `&`:

  ```bash
  corpus=$(mktemp -d)/corpus
  (cd backend/viewer && uv run python -m ord_viewer.testing "$corpus")
  (cd backend/viewer && ORD_VIEWER_CORPUS_DIR="$corpus" \
    uv run uvicorn --factory ord_viewer.testing:e2e_app --host 127.0.0.1 --port 8001) &
  (cd frontend && npm run build -w apps/viewer && npm run preview -w apps/viewer -- --host 127.0.0.1) &
  (cd frontend && npx -w apps/viewer playwright install chromium && npm run test:e2e -w apps/viewer)
  ```

  Expected: every spec passes but the screenshots, which skip outside CI. Stop both
  servers afterwards.

- [ ] **Step 6: The CI job.** In `.github/workflows/tests.yml`, after `test_e2e`, add:

  ```yaml
    test_e2e_viewer:
      runs-on: ubuntu-latest
      steps:
        - name: Check out repository
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

        - name: Install uv
          uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
          with:
            python-version: "3.12"

        - name: Install the backend
          working-directory: backend/viewer
          run: uv sync --frozen --no-build

        - name: Derive the test corpus
          working-directory: backend/viewer
          run: uv run --frozen --no-build python -m ord_viewer.testing "$RUNNER_TEMP/corpus"

        - name: Set up Node
          uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
          with:
            node-version: 22

        - name: Install the frontend
          working-directory: frontend
          run: npm ci --ignore-scripts

        - name: Install Playwright's browser
          working-directory: frontend
          run: node_modules/.bin/playwright install --with-deps chromium

        - name: Build the viewer
          working-directory: frontend
          run: npm run build -w apps/viewer

        # Background processes do not outlive their step on GitHub's runners, so the
        # servers and the tests share one.
        - name: Serve the viewer and run its end-to-end tests
          env:
            ORD_VIEWER_CORPUS_DIR: ${{ runner.temp }}/corpus
          run: |
            nohup uv run --directory backend/viewer --frozen --no-build \
              uvicorn --factory ord_viewer.testing:e2e_app --host 127.0.0.1 --port 8001 \
              > "$RUNNER_TEMP/backend.log" 2>&1 &
            nohup npm --prefix frontend -w apps/viewer run preview -- --host 127.0.0.1 \
              > "$RUNNER_TEMP/preview.log" 2>&1 &
            wait_for() {
              for _ in $(seq 1 60); do
                if curl -sf --max-time 5 "$1" > /dev/null; then
                  return 0
                fi
                sleep 2
              done
              echo "$1 did not answer:"
              cat "$2"
              return 1
            }
            wait_for http://127.0.0.1:8001/api/health "$RUNNER_TEMP/backend.log"
            wait_for http://127.0.0.1:4174/ "$RUNNER_TEMP/preview.log"
            npm --prefix frontend -w apps/viewer run test:e2e

        - name: Server logs (on failure)
          if: failure()
          run: cat "$RUNNER_TEMP/backend.log" "$RUNNER_TEMP/preview.log" || true

        - name: Upload the Playwright report (on failure)
          if: failure()
          uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
          with:
            name: playwright-report-viewer
            path: |
              frontend/apps/viewer/playwright-report/
              frontend/apps/viewer/test-results/
              frontend/apps/viewer/e2e/*-snapshots/
            retention-days: 7
  ```

  Run `actionlint .github/workflows/tests.yml`. Expected: clean.

- [ ] **Step 7: Commit.**

  ```bash
  git add backend/viewer/ord_viewer/testing.py backend/viewer/ord_viewer/testing_test.py \
    frontend/apps/viewer/package.json frontend/package-lock.json \
    frontend/apps/viewer/playwright.config.ts frontend/apps/viewer/e2e .github/workflows/tests.yml
  git commit -m "Run the viewer end to end against its backend over the fixture corpus"
  ```

  The first CI run has no screenshot baselines: it writes them and fails. Download the
  run's `playwright-report-viewer` artifact, check each image, commit them under
  `frontend/apps/viewer/e2e/screenshots.spec.ts-snapshots/`, and push.

### Task F4.9: Floors, docs, and the PR

- [ ] **Step 1: The coverage floors.** Run `npx vitest run --coverage` in
  `frontend/apps/viewer`, and set each threshold in `vite.config.ts` to the measured
  percentage rounded down. A file the unit tests cannot reach, such as `main.tsx`, stays
  excluded as F2 left it.
- [ ] **Step 2: The docs.**
  - `CLAUDE.md`:
    - the `apps/viewer/` bullet names the pages (`pages/`), the record-to-provider path
      (`reaction/`), and the end-to-end specs (`e2e/`);
    - the Frontend section gains the end-to-end commands from F4.8's Step 5;
    - the CI gates' Tests line gains `test_e2e_viewer`.
  - `README.md`'s Viewer section gains the same commands.
  - Run `npm run lint:check`, `npm run typecheck`, and `npm run build -w apps/viewer`
    from `frontend/`, and `uvx pre-commit run --all-files` from the root.
- [ ] **Step 3: Open the PR.** Title "Browse the corpus in the viewer: datasets,
  reactions, and selected sets". Its Notes say that `test_e2e_viewer` must be added to
  the `main` ruleset's required checks, and how the screenshot baselines were made. Bind
  it, turn on auto-fix, and run `review-pr`.

---

## PR F5: search

Branch `viewer-search`, in its own worktree from `origin/main` once F4 has merged.

### Task F5.1: The form's state, to and from the URL

**Files:**

- Create: `frontend/apps/viewer/src/search/form.ts`,
  `frontend/apps/viewer/src/search/form.test.ts`

**Interfaces:**

- Produces:
  - the types `StructureTarget` (`'input' | 'output'`), `MatchMode`
    (`'exact' | 'similar' | 'substructure' | 'smarts'`), `StructureField`
    (`{pattern, target, mode}`), `NumberRange` (`[number, number]`), and `SearchForm`;
  - the constants `DEFAULT_SIMILARITY = 0.5`, `DEFAULT_LIMIT = 100`, `MAX_LIMIT = 1000`,
    `FULL_RANGE`, and `EMPTY_FORM`;
  - `formFromParams(params: URLSearchParams): SearchForm`;
  - `paramsFromForm(form: SearchForm): URLSearchParams`.

- [ ] **Step 1: Write the failing tests.** `src/search/form.test.ts`:

  ```ts
  import { describe, expect, it } from 'vitest';
  import {
    EMPTY_FORM,
    formFromParams,
    paramsFromForm,
    type SearchForm,
  } from '#search/form.ts';

  function parse(query: string): SearchForm {
    return formFromParams(new URLSearchParams(query));
  }

  function component(pattern: string, target: string, mode: string): string {
    return `component=${encodeURIComponent(JSON.stringify({ pattern, target, mode }))}`;
  }

  describe('formFromParams', () => {
    it('reads no parameters as the empty form', () => {
      expect(parse('')).toEqual(EMPTY_FORM);
    });

    it("reads ord-interface's JSON components", () => {
      expect(parse(component('CCN', 'input', 'exact')).structures).toEqual([
        { pattern: 'CCN', target: 'input', mode: 'exact' },
      ]);
    });

    it.each([
      ['CCN;input;exact', { pattern: 'CCN', target: 'input', mode: 'exact' }],
      ['CCN;OUTPUT;SIMILAR', { pattern: 'CCN', target: 'output', mode: 'similar' }],
      ['[C;R]Cl;input;smarts', { pattern: '[C;R]Cl', target: 'input', mode: 'smarts' }],
    ])('reads the legacy component %j, splitting from the right', (value, structure) => {
      expect(parse(`component=${encodeURIComponent(value)}`).structures).toEqual([structure]);
    });

    it.each([
      ['CCN;input'],
      ['CCN;sideways;exact'],
      ['CCN;input;fuzzy'],
      ['{"pattern": "CCN"}'],
      ['{not json'],
    ])('drops the component %j, which names no structure it can search', value => {
      expect(parse(`component=${encodeURIComponent(value)}`).structures).toEqual([]);
    });

    it('reads every other field', () => {
      const form = parse(
        [
          'use_stereochemistry=true',
          'similarity=0.7',
          'reaction_smarts=%5BN%3A1%5D%3E%3E%5BN%3A1%5D',
          'min_yield=40',
          'max_yield=90',
          'min_conversion=10',
          'max_conversion=20',
          'dataset_id=ord_dataset-1',
          'dataset_id=ord_dataset-2',
          'doi=10.1%2Fx',
          'reaction_id=ord-1',
          'limit=250',
        ].join('&'),
      );
      expect(form).toEqual({
        ...EMPTY_FORM,
        useStereochemistry: true,
        similarity: 0.7,
        reactionSmarts: ['[N:1]>>[N:1]'],
        yieldRange: [40, 90],
        conversionRange: [10, 20],
        datasetIds: ['ord_dataset-1', 'ord_dataset-2'],
        dois: ['10.1/x'],
        reactionIds: ['ord-1'],
        limit: 250,
      });
    });

    it.each([
      ['similarity=0', 'similarity', 0.5],
      ['similarity=1.5', 'similarity', 0.5],
      ['similarity=abc', 'similarity', 0.5],
      ['limit=0', 'limit', 100],
      ['limit=5000', 'limit', 1000],
      ['limit=12.7', 'limit', 12],
    ])('reads %j as a %s of %j', (query, key, value) => {
      expect(parse(query)[key as keyof SearchForm]).toBe(value);
    });

    it('reads a range past its bounds as within them', () => {
      expect(parse('min_yield=-5&max_yield=150').yieldRange).toEqual([0, 100]);
    });
  });

  describe('paramsFromForm', () => {
    it('writes nothing but the limit for the empty form', () => {
      expect(paramsFromForm(EMPTY_FORM).toString()).toBe('limit=100');
    });

    it('writes the stereochemistry and similarity only with a structure', () => {
      const params = paramsFromForm({
        ...EMPTY_FORM,
        structures: [{ pattern: 'CCN', target: 'input', mode: 'similar' }],
      });
      expect(params.getAll('component')).toEqual([
        JSON.stringify({ pattern: 'CCN', target: 'input', mode: 'similar' }),
      ]);
      expect(params.get('use_stereochemistry')).toBe('false');
      expect(params.get('similarity')).toBe('0.5');
    });

    it('writes a range only when it is narrower than 0 to 100', () => {
      const params = paramsFromForm({ ...EMPTY_FORM, yieldRange: [50, 100] });
      expect(params.get('min_yield')).toBe('50');
      expect(params.get('max_yield')).toBe('100');
      expect(params.has('min_conversion')).toBe(false);
    });

    it('round-trips a full form', () => {
      const form: SearchForm = {
        structures: [
          { pattern: 'c1ccccc1', target: 'output', mode: 'substructure' },
          { pattern: '[C;R]Cl', target: 'input', mode: 'smarts' },
        ],
        useStereochemistry: true,
        similarity: 0.6,
        reactionSmarts: ['[N:1]>>[N:1]'],
        yieldRange: [10, 90],
        conversionRange: [0, 50],
        datasetIds: ['ord_dataset-1'],
        dois: ['10.1/x'],
        reactionIds: ['ord-1', 'ord-2'],
        limit: 300,
      };
      expect(formFromParams(paramsFromForm(form))).toEqual(form);
    });
  });
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/search
  ```

  Expected: FAIL, `Failed to resolve import "#search/form.ts"`.

- [ ] **Step 3: Write the form's state.** `src/search/form.ts`:

  ```ts
  /** Which side of a reaction a structure is looked for on. */
  export type StructureTarget = 'input' | 'output';

  /** How a structure matches: as the same compound, by similarity, or as a pattern. */
  export type MatchMode = 'exact' | 'similar' | 'substructure' | 'smarts';

  export interface StructureField {
    /** A SMILES, or a SMARTS in the smarts mode. */
    pattern: string;
    target: StructureTarget;
    mode: MatchMode;
  }

  /** Inclusive bounds, in percent. */
  export type NumberRange = [number, number];

  /** The search form, as the URL holds it under ord-interface's parameter names. */
  export interface SearchForm {
    structures: Array<StructureField>;
    useStereochemistry: boolean;
    /** The Tanimoto threshold for similar structures, in (0, 1]. */
    similarity: number;
    reactionSmarts: Array<string>;
    yieldRange: NumberRange;
    conversionRange: NumberRange;
    datasetIds: Array<string>;
    dois: Array<string>;
    reactionIds: Array<string>;
    /** The most reactions to return, from 1 to MAX_LIMIT. */
    limit: number;
  }

  export const DEFAULT_SIMILARITY = 0.5;
  export const DEFAULT_LIMIT = 100;
  /** The backend's bound on a result's rows. */
  export const MAX_LIMIT = 1000;
  export const FULL_RANGE: NumberRange = [0, 100];

  export const EMPTY_FORM: SearchForm = {
    structures: [],
    useStereochemistry: false,
    similarity: DEFAULT_SIMILARITY,
    reactionSmarts: [],
    yieldRange: FULL_RANGE,
    conversionRange: FULL_RANGE,
    datasetIds: [],
    dois: [],
    reactionIds: [],
    limit: DEFAULT_LIMIT,
  };

  const TARGETS: ReadonlyArray<StructureTarget> = ['input', 'output'];
  const MODES: ReadonlyArray<MatchMode> = ['exact', 'similar', 'substructure', 'smarts'];

  /** The structure named, or null for a target or mode ord-interface would not accept. */
  function structureOf(pattern: unknown, target: unknown, mode: unknown): StructureField | null {
    if (typeof pattern !== 'string' || typeof target !== 'string' || typeof mode !== 'string') {
      return null;
    }
    const knownTarget = TARGETS.find(value => value === target.toLowerCase());
    const knownMode = MODES.find(value => value === mode.toLowerCase());
    return knownTarget && knownMode
      ? { pattern, target: knownTarget, mode: knownMode }
      : null;
  }

  /**
   * One component value: a JSON object, or ord-interface's legacy "pattern;target;mode",
   * split from the right since a SMARTS may hold ";".
   */
  function parseComponent(value: string): StructureField | null {
    const trimmed = value.trim();
    if (trimmed.startsWith('{')) {
      try {
        const { pattern, target, mode } = JSON.parse(trimmed) as Record<string, unknown>;
        return structureOf(pattern, target, mode);
      } catch {
        return null;
      }
    }
    const parts = trimmed.split(';');
    if (parts.length < 3) {
      return null;
    }
    const mode = parts.pop();
    const target = parts.pop();
    return structureOf(parts.join(';'), target, mode);
  }

  function percent(value: string | null, fallback: number): number {
    const number = value === null ? Number.NaN : Number(value);
    return Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : fallback;
  }

  function rangeOf(params: URLSearchParams, low: string, high: string): NumberRange {
    return [percent(params.get(low), 0), percent(params.get(high), 100)];
  }

  function similarityOf(value: string | null): number {
    const number = value === null ? Number.NaN : Number(value);
    return number > 0 && number <= 1 ? number : DEFAULT_SIMILARITY;
  }

  function limitOf(value: string | null): number {
    const number = value === null ? Number.NaN : Math.floor(Number(value));
    return number >= 1 ? Math.min(number, MAX_LIMIT) : DEFAULT_LIMIT;
  }

  /** The form a URL's parameters describe; a value it cannot read keeps its default. */
  export function formFromParams(params: URLSearchParams): SearchForm {
    return {
      structures: params
        .getAll('component')
        .map(parseComponent)
        .filter((structure): structure is StructureField => structure !== null),
      useStereochemistry: params.get('use_stereochemistry') === 'true',
      similarity: similarityOf(params.get('similarity')),
      reactionSmarts: params.getAll('reaction_smarts'),
      yieldRange: rangeOf(params, 'min_yield', 'max_yield'),
      conversionRange: rangeOf(params, 'min_conversion', 'max_conversion'),
      datasetIds: params.getAll('dataset_id'),
      dois: params.getAll('doi'),
      reactionIds: params.getAll('reaction_id'),
      limit: limitOf(params.get('limit')),
    };
  }

  function isFullRange([low, high]: NumberRange): boolean {
    return low === FULL_RANGE[0] && high === FULL_RANGE[1];
  }

  /** The URL's parameters for a form, as ord-interface's search page wrote them. */
  export function paramsFromForm(form: SearchForm): URLSearchParams {
    const params = new URLSearchParams();
    for (const { pattern, target, mode } of form.structures) {
      params.append('component', JSON.stringify({ pattern, target, mode }));
    }
    if (form.structures.length > 0) {
      params.set('use_stereochemistry', String(form.useStereochemistry));
      params.set('similarity', String(form.similarity));
    }
    for (const smarts of form.reactionSmarts) {
      params.append('reaction_smarts', smarts);
    }
    if (!isFullRange(form.yieldRange)) {
      params.set('min_yield', String(form.yieldRange[0]));
      params.set('max_yield', String(form.yieldRange[1]));
    }
    if (!isFullRange(form.conversionRange)) {
      params.set('min_conversion', String(form.conversionRange[0]));
      params.set('max_conversion', String(form.conversionRange[1]));
    }
    for (const datasetId of form.datasetIds) {
      params.append('dataset_id', datasetId);
    }
    for (const doi of form.dois) {
      params.append('doi', doi);
    }
    for (const reactionId of form.reactionIds) {
      params.append('reaction_id', reactionId);
    }
    params.set('limit', String(form.limit));
    return params;
  }
  ```

  The round trip in Step 1 holds because `paramsFromForm` writes the stereochemistry
  whenever a structure is set; a form with no structures but `useStereochemistry: true`
  does not round-trip, since ord-interface's URLs carried it only with a structure.

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/search
  git commit -m "Read and write the search form's state in ord-interface's URL parameters"
  ```

### Task F5.2: The compiler

**Files:**

- Create: `frontend/apps/viewer/src/search/compile.ts`,
  `frontend/apps/viewer/src/search/compile.test.ts`

**Interfaces:**

- Consumes: `SearchForm`, `FULL_RANGE` (F5.1); `Query` (F2).
- Produces: `compileQuery(form: SearchForm): Query | null`, null when the form sets
  nothing, since a `Query` with no `where` is every reaction in the corpus.

- [ ] **Step 1: Write the failing tests.** `src/search/compile.test.ts`, one case per row
  of the design's table, with the shapes F4–F6's planning ran against the fixture corpus:

  ```ts
  import { describe, expect, it } from 'vitest';
  import { compileQuery } from '#search/compile.ts';
  import { EMPTY_FORM, type SearchForm } from '#search/form.ts';

  const ORDER = [{ key: 'reaction_id' }];

  function where(form: Partial<SearchForm>) {
    return compileQuery({ ...EMPTY_FORM, ...form })?.where;
  }

  function inputs(predicate: object) {
    return { op: 'exists', path: 'inputs.components', where: predicate };
  }

  describe('compileQuery', () => {
    it('compiles nothing for an empty form', () => {
      expect(compileQuery(EMPTY_FORM)).toBeNull();
    });

    it('compiles nothing for a blank structure and full ranges', () => {
      expect(
        compileQuery({
          ...EMPTY_FORM,
          structures: [{ pattern: '  ', target: 'input', mode: 'exact' }],
        }),
      ).toBeNull();
    });

    it('orders by reaction ID and keeps the limit', () => {
      expect(compileQuery({ ...EMPTY_FORM, reactionIds: ['ord-1'], limit: 250 })).toEqual({
        where: { op: 'or', clauses: [{ op: 'eq', path: 'reaction_id', value: { literal: 'ord-1' } }] },
        order_by: ORDER,
        limit: 250,
      });
    });

    it.each([
      [
        'exact',
        { op: 'same_compound', path: 'smiles', smiles: 'CCN' },
      ],
      [
        'similar',
        { op: 'similarity', path: 'smiles', smiles: 'CCN', threshold: 0.5 },
      ],
      [
        'substructure',
        { op: 'substructure', path: 'smiles', smarts: 'CCN', chirality: false },
      ],
      [
        'smarts',
        { op: 'substructure', path: 'smiles', smarts: 'CCN', chirality: false },
      ],
    ] as const)('compiles an %s input structure', (mode, predicate) => {
      expect(
        where({ structures: [{ pattern: 'CCN', target: 'input', mode }] }),
      ).toEqual(inputs(predicate));
    });

    it('looks for a product structure among the outcomes', () => {
      expect(
        where({ structures: [{ pattern: 'CCN', target: 'output', mode: 'exact' }] }),
      ).toEqual({
        op: 'exists',
        path: 'outcomes.products',
        where: { op: 'same_compound', path: 'smiles', smiles: 'CCN' },
      });
    });

    it('carries the similarity threshold and stereochemistry', () => {
      expect(
        where({
          structures: [
            { pattern: 'CCN', target: 'input', mode: 'similar' },
            { pattern: 'N', target: 'input', mode: 'substructure' },
          ],
          similarity: 0.8,
          useStereochemistry: true,
        }),
      ).toEqual({
        op: 'and',
        clauses: [
          inputs({ op: 'similarity', path: 'smiles', smiles: 'CCN', threshold: 0.8 }),
          inputs({ op: 'substructure', path: 'smiles', smarts: 'N', chirality: true }),
        ],
      });
    });

    it('compiles a reaction SMARTS', () => {
      expect(where({ reactionSmarts: ['[N:1]>>[N:1]'] })).toEqual({
        op: 'reaction_smarts',
        smarts: '[N:1]>>[N:1]',
        chirality: false,
      });
    });

    it('compiles a yield range over the products\' yield measurements', () => {
      expect(where({ yieldRange: [70, 100] })).toEqual({
        op: 'exists',
        path: 'outcomes.products',
        where: {
          op: 'exists',
          path: 'measurements',
          where: {
            op: 'and',
            clauses: [
              { op: 'eq', path: 'type', value: { literal: 'YIELD' } },
              { op: 'ge', path: 'percentage.value', value: { literal: 70 } },
              { op: 'le', path: 'percentage.value', value: { literal: 100 } },
            ],
          },
        },
      });
    });

    it("compiles a conversion range over the outcomes' conversion", () => {
      expect(where({ conversionRange: [0, 50] })).toEqual({
        op: 'exists',
        path: 'outcomes',
        where: {
          op: 'and',
          clauses: [
            { op: 'ge', path: 'conversion.value', value: { literal: 0 } },
            { op: 'le', path: 'conversion.value', value: { literal: 50 } },
          ],
        },
      });
    });

    it.each([
      ['datasetIds', 'dataset_id'],
      ['dois', 'provenance.doi'],
      ['reactionIds', 'reaction_id'],
    ] as const)('matches any of the %s', (field, path) => {
      expect(where({ [field]: ['a', 'b'] })).toEqual({
        op: 'or',
        clauses: [
          { op: 'eq', path, value: { literal: 'a' } },
          { op: 'eq', path, value: { literal: 'b' } },
        ],
      });
    });

    it('joins the fields with and', () => {
      const compiled = where({ datasetIds: ['a'], yieldRange: [50, 100] });
      expect(compiled).toMatchObject({ op: 'and' });
      expect((compiled as { clauses: Array<unknown> }).clauses).toHaveLength(2);
    });
  });
  ```

- [ ] **Step 2: Run them to see them fail.** `npx vitest run src/search/compile.test.ts`.
  Expected: FAIL, `Failed to resolve import "#search/compile.ts"`.

- [ ] **Step 3: Write the compiler.** `src/search/compile.ts`:

  ```ts
  import type { Query } from '#api/types.ts';
  import {
    FULL_RANGE,
    type NumberRange,
    type SearchForm,
    type StructureField,
  } from '#search/form.ts';

  /** One predicate of the grammar. */
  type Predicate = NonNullable<Query['where']>;

  const STRUCTURE_PATHS = { input: 'inputs.components', output: 'outcomes.products' };

  function structurePredicate(
    { pattern, mode }: StructureField,
    form: SearchForm,
  ): Predicate {
    switch (mode) {
      case 'exact':
        return { op: 'same_compound', path: 'smiles', smiles: pattern };
      case 'similar':
        return { op: 'similarity', path: 'smiles', smiles: pattern, threshold: form.similarity };
      // A substructure's SMILES is read as SMARTS, as the cartridge's SMILES query read it
      // for most patterns.
      case 'substructure':
      case 'smarts':
        return {
          op: 'substructure',
          path: 'smiles',
          smarts: pattern,
          chirality: form.useStereochemistry,
        };
    }
  }

  function between(path: string, [low, high]: NumberRange): Array<Predicate> {
    return [
      { op: 'ge', path, value: { literal: low } },
      { op: 'le', path, value: { literal: high } },
    ];
  }

  function isFullRange([low, high]: NumberRange): boolean {
    return low === FULL_RANGE[0] && high === FULL_RANGE[1];
  }

  function anyOf(path: string, values: ReadonlyArray<string>): Array<Predicate> {
    return values.length === 0
      ? []
      : [
          {
            op: 'or',
            clauses: values.map(value => ({ op: 'eq' as const, path, value: { literal: value } })),
          },
        ];
  }

  /**
   * The form as a query: each field set adds a clause, and the clauses are joined by and.
   *
   * Returns null when nothing is set. Matches come back ordered by reaction ID, at most
   * the form's limit.
   */
  export function compileQuery(form: SearchForm): Query | null {
    const clauses: Array<Predicate> = [];
    for (const structure of form.structures) {
      if (structure.pattern.trim() !== '') {
        clauses.push({
          op: 'exists',
          path: STRUCTURE_PATHS[structure.target],
          where: structurePredicate({ ...structure, pattern: structure.pattern.trim() }, form),
        });
      }
    }
    for (const smarts of form.reactionSmarts) {
      clauses.push({ op: 'reaction_smarts', smarts, chirality: form.useStereochemistry });
    }
    if (!isFullRange(form.yieldRange)) {
      clauses.push({
        op: 'exists',
        path: 'outcomes.products',
        where: {
          op: 'exists',
          path: 'measurements',
          where: {
            op: 'and',
            clauses: [
              { op: 'eq', path: 'type', value: { literal: 'YIELD' } },
              ...between('percentage.value', form.yieldRange),
            ],
          },
        },
      });
    }
    if (!isFullRange(form.conversionRange)) {
      clauses.push({
        op: 'exists',
        path: 'outcomes',
        where: { op: 'and', clauses: between('conversion.value', form.conversionRange) },
      });
    }
    clauses.push(
      ...anyOf('dataset_id', form.datasetIds),
      ...anyOf('provenance.doi', form.dois),
      ...anyOf('reaction_id', form.reactionIds),
    );
    if (clauses.length === 0) {
      return null;
    }
    return {
      where: clauses.length === 1 ? clauses[0] : { op: 'and', clauses },
      order_by: [{ key: 'reaction_id' }],
      limit: form.limit,
    };
  }
  ```

  If `tsc` rejects a literal's union (the generated types name each predicate's `op`
  as a literal), add `as const` to the literal rather than widening `Predicate`.

- [ ] **Step 4: Run the tests to see them pass**, and `npm run typecheck` from
  `frontend/`. Expected: every test passes, and `tsc` is clean, which proves each
  compiled shape against the grammar's own types.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/search/compile.ts frontend/apps/viewer/src/search/compile.test.ts
  git commit -m "Compile the search form to a Query in the browser"
  ```

### Task F5.3: The form

**Files:**

- Create: `frontend/apps/viewer/src/search/SearchFormPanel.tsx`,
  `frontend/apps/viewer/src/search/SearchFormPanel.test.tsx`

**Interfaces:**

- Consumes: `SearchForm`, `EMPTY_FORM`, `MAX_LIMIT` (F5.1); `StructureDialog` from
  `@open-reaction-database/ui/ketcher` (F1).
- Produces: `SearchFormPanel({initial, onSearch})`, where `onSearch(form)` receives the
  form when Search is clicked.

- [ ] **Step 1: Write the failing tests.** `src/search/SearchFormPanel.test.tsx`:

  ```tsx
  import { describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { fireEvent } from '@testing-library/react';
  import { renderAt } from '#test/render.tsx';
  import { EMPTY_FORM } from '#search/form.ts';
  import { SearchFormPanel } from '#search/SearchFormPanel.tsx';

  // Ketcher cannot run in happy-dom; this dialog saves benzene, in the format asked for.
  vi.mock('@open-reaction-database/ui/ketcher', () => ({
    StructureDialog: ({
      opened,
      format,
      onSave,
    }: {
      opened: boolean;
      format: string;
      onSave: (structure: string) => void;
    }) =>
      opened ? (
        <div role="dialog">
          <button
            type="button"
            onClick={() => onSave(format === 'smarts' ? 'c1ccccc1' : 'C1=CC=CC=C1')}
          >
            Save drawing
          </button>
        </div>
      ) : null,
  }));

  function setUp(initial = EMPTY_FORM) {
    const onSearch = vi.fn();
    const user = userEvent.setup();
    const view = renderAt('/search', <SearchFormPanel initial={initial} onSearch={onSearch} />);
    return { ...view, onSearch, user };
  }

  describe('SearchFormPanel', () => {
    it('searches for a typed structure', async () => {
      const { getByRole, onSearch, user } = setUp();
      await user.click(getByRole('button', { name: 'Add a structure' }));
      await user.type(getByRole('textbox', { name: 'Structure 1' }), 'CCN');
      await user.selectOptions(getByRole('combobox', { name: 'Match for structure 1' }), 'similar');
      await user.selectOptions(getByRole('combobox', { name: 'Side for structure 1' }), 'output');
      await user.click(getByRole('button', { name: 'Search' }));
      expect(onSearch).toHaveBeenCalledWith(
        expect.objectContaining({
          structures: [{ pattern: 'CCN', target: 'output', mode: 'similar' }],
        }),
      );
    });

    it('draws a structure', async () => {
      const { getByRole, user } = setUp();
      await user.click(getByRole('button', { name: 'Add a structure' }));
      await user.click(getByRole('button', { name: 'Draw structure 1' }));
      await user.click(getByRole('button', { name: 'Save drawing' }));
      expect(getByRole('textbox', { name: 'Structure 1' })).toHaveValue('C1=CC=CC=C1');
    });

    it('draws a SMARTS in SMARTS mode', async () => {
      const { getByRole, user } = setUp();
      await user.click(getByRole('button', { name: 'Add a structure' }));
      await user.selectOptions(getByRole('combobox', { name: 'Match for structure 1' }), 'smarts');
      await user.click(getByRole('button', { name: 'Draw structure 1' }));
      await user.click(getByRole('button', { name: 'Save drawing' }));
      expect(getByRole('textbox', { name: 'Structure 1' })).toHaveValue('c1ccccc1');
    });

    it('asks for the threshold only for a similar structure', async () => {
      const { getByRole, queryByRole, user } = setUp();
      await user.click(getByRole('button', { name: 'Add a structure' }));
      expect(queryByRole('textbox', { name: 'Similarity threshold' })).not.toBeInTheDocument();
      await user.selectOptions(getByRole('combobox', { name: 'Match for structure 1' }), 'similar');
      expect(getByRole('textbox', { name: 'Similarity threshold' })).toHaveValue('0.5');
    });

    it('removes a structure', async () => {
      const { getByRole, queryByRole, user } = setUp();
      await user.click(getByRole('button', { name: 'Add a structure' }));
      await user.click(getByRole('button', { name: 'Remove structure 1' }));
      expect(queryByRole('textbox', { name: 'Structure 1' })).not.toBeInTheDocument();
    });

    it('starts from the form it is given', () => {
      const { getByRole } = setUp({
        ...EMPTY_FORM,
        structures: [{ pattern: 'CCN', target: 'input', mode: 'exact' }],
        reactionSmarts: ['[N:1]>>[N:1]', '[O:1]>>[O:1]'],
        reactionIds: ['ord-1'],
        limit: 250,
      });
      expect(getByRole('textbox', { name: 'Structure 1' })).toHaveValue('CCN');
      expect(getByRole('textbox', { name: 'Reaction SMARTS' })).toHaveValue(
        '[N:1]>>[N:1]\n[O:1]>>[O:1]',
      );
      expect(getByRole('textbox', { name: 'Limit' })).toHaveValue('250');
    });

    it('reads one reaction SMARTS per line, ignoring blank ones', async () => {
      const { getByRole, onSearch, user } = setUp();
      await user.type(getByRole('textbox', { name: 'Reaction SMARTS' }), 'A>>B{Enter}{Enter}C>>D');
      await user.click(getByRole('button', { name: 'Search' }));
      expect(onSearch.mock.calls[0][0].reactionSmarts).toEqual(['A>>B', 'C>>D']);
    });

    it('moves a yield bound with the keyboard', async () => {
      const { getAllByRole, getByRole, onSearch, user } = setUp();
      const [yieldLow] = getAllByRole('slider');
      fireEvent.keyDown(yieldLow, { key: 'ArrowRight' });
      await user.click(getByRole('button', { name: 'Search' }));
      expect(onSearch.mock.calls[0][0].yieldRange).toEqual([1, 100]);
    });

    it('clears the form', async () => {
      const { getByRole, queryByRole, user } = setUp({
        ...EMPTY_FORM,
        structures: [{ pattern: 'CCN', target: 'input', mode: 'exact' }],
      });
      await user.click(getByRole('button', { name: 'Clear' }));
      expect(queryByRole('textbox', { name: 'Structure 1' })).not.toBeInTheDocument();
    });
  });
  ```

  Mantine's `TagsInput` renders a text input for new values; the IDs and DOIs fields are
  exercised end to end in F5.6 instead, since typing into it in happy-dom depends on its
  dropdown's timing.

- [ ] **Step 2: Run them to see them fail.** `npx vitest run src/search/SearchFormPanel.test.tsx`.
  Expected: FAIL, `Failed to resolve import "#search/SearchFormPanel.tsx"`.

- [ ] **Step 3: Write the panel.** `src/search/SearchFormPanel.tsx`:

  ```tsx
  import {
    Button,
    Checkbox,
    Group,
    NativeSelect,
    NumberInput,
    RangeSlider,
    Stack,
    TagsInput,
    Text,
    Textarea,
    TextInput,
  } from '@mantine/core';
  import { StructureDialog } from '@open-reaction-database/ui/ketcher';
  import { useState } from 'react';
  import {
    EMPTY_FORM,
    MAX_LIMIT,
    type MatchMode,
    type NumberRange,
    type SearchForm,
    type StructureField,
    type StructureTarget,
  } from '#search/form.ts';

  const MODE_OPTIONS = [
    { label: 'Exact', value: 'exact' },
    { label: 'Similar', value: 'similar' },
    { label: 'Substructure', value: 'substructure' },
    { label: 'SMARTS', value: 'smarts' },
  ];

  const TARGET_OPTIONS = [
    { label: 'Input', value: 'input' },
    { label: 'Product', value: 'output' },
  ];

  interface StructureRowProps {
    index: number;
    structure: StructureField;
    onChange: (structure: StructureField) => void;
    onRemove: () => void;
  }

  function StructureRow({ index, structure, onChange, onRemove }: Readonly<StructureRowProps>) {
    const [drawing, setDrawing] = useState(false);
    const name = `structure ${index + 1}`;
    return (
      <Stack gap={4}>
        <TextInput
          label={`Structure ${index + 1}`}
          placeholder={structure.mode === 'smarts' ? 'SMARTS' : 'SMILES'}
          value={structure.pattern}
          onChange={event => onChange({ ...structure, pattern: event.currentTarget.value })}
        />
        <Group gap="xs">
          <NativeSelect
            aria-label={`Side for ${name}`}
            size="xs"
            data={TARGET_OPTIONS}
            value={structure.target}
            onChange={event =>
              onChange({ ...structure, target: event.currentTarget.value as StructureTarget })
            }
          />
          <NativeSelect
            aria-label={`Match for ${name}`}
            size="xs"
            data={MODE_OPTIONS}
            value={structure.mode}
            onChange={event =>
              onChange({ ...structure, mode: event.currentTarget.value as MatchMode })
            }
          />
          <Button
            size="xs"
            variant="default"
            aria-label={`Draw ${name}`}
            onClick={() => setDrawing(true)}
          >
            Draw
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color="red"
            aria-label={`Remove ${name}`}
            onClick={onRemove}
          >
            Remove
          </Button>
        </Group>
        <StructureDialog
          opened={drawing}
          onClose={() => setDrawing(false)}
          initial={structure.pattern}
          format={structure.mode === 'smarts' ? 'smarts' : 'smiles'}
          onSave={pattern => onChange({ ...structure, pattern })}
        />
      </Stack>
    );
  }

  function RangeField({
    label,
    value,
    onChange,
  }: Readonly<{ label: string; value: NumberRange; onChange: (value: NumberRange) => void }>) {
    return (
      <Stack gap={4}>
        <Text size="sm">
          {label}: {value[0]}% to {value[1]}%
        </Text>
        <RangeSlider
          min={0}
          max={100}
          minRange={0}
          value={value}
          onChange={onChange}
          label={null}
          thumbFromLabel={`${label}, at least`}
          thumbToLabel={`${label}, at most`}
        />
      </Stack>
    );
  }

  function lines(text: string): Array<string> {
    return text
      .split('\n')
      .map(line => line.trim())
      .filter(line => line !== '');
  }

  interface SearchFormPanelProps {
    initial: SearchForm;
    onSearch: (form: SearchForm) => void;
  }

  /** The search form: structures, reaction SMARTS, ranges, and IDs, joined by and. */
  export function SearchFormPanel({ initial, onSearch }: Readonly<SearchFormPanelProps>) {
    const [form, setForm] = useState(initial);
    // Reaction SMARTS are edited as text, so a line being typed survives until Search.
    const [smartsText, setSmartsText] = useState(initial.reactionSmarts.join('\n'));
    const update = (patch: Partial<SearchForm>) => setForm(current => ({ ...current, ...patch }));
    const setStructure = (index: number, structure: StructureField) =>
      update({ structures: form.structures.map((old, i) => (i === index ? structure : old)) });
    return (
      <Stack gap="md">
        {form.structures.map((structure, index) => (
          <StructureRow
            // Rows are keyed by position; removing one re-keys the rest, which is fine
            // for fields that hold no state of their own beyond the dialog.
            key={index}
            index={index}
            structure={structure}
            onChange={changed => setStructure(index, changed)}
            onRemove={() =>
              update({ structures: form.structures.filter((_, i) => i !== index) })
            }
          />
        ))}
        <Button
          variant="default"
          onClick={() =>
            update({
              structures: [...form.structures, { pattern: '', target: 'input', mode: 'exact' }],
            })
          }
        >
          Add a structure
        </Button>
        <Checkbox
          label="Match stereochemistry"
          checked={form.useStereochemistry}
          onChange={event => update({ useStereochemistry: event.currentTarget.checked })}
        />
        {form.structures.some(structure => structure.mode === 'similar') && (
          <NumberInput
            label="Similarity threshold"
            min={0.05}
            max={1}
            step={0.05}
            decimalScale={2}
            value={form.similarity}
            onChange={value => update({ similarity: Number(value) || form.similarity })}
          />
        )}
        <Textarea
          label="Reaction SMARTS"
          description="One per line"
          autosize
          minRows={2}
          value={smartsText}
          onChange={event => setSmartsText(event.currentTarget.value)}
        />
        <RangeField
          label="Yield"
          value={form.yieldRange}
          onChange={yieldRange => update({ yieldRange })}
        />
        <RangeField
          label="Conversion"
          value={form.conversionRange}
          onChange={conversionRange => update({ conversionRange })}
        />
        <TagsInput
          label="Dataset IDs"
          value={form.datasetIds}
          onChange={datasetIds => update({ datasetIds })}
          splitChars={[',', ' ']}
        />
        <TagsInput
          label="DOIs"
          value={form.dois}
          onChange={dois => update({ dois })}
          splitChars={[',', ' ']}
        />
        <TagsInput
          label="Reaction IDs"
          value={form.reactionIds}
          onChange={reactionIds => update({ reactionIds })}
          splitChars={[',', ' ']}
        />
        <NumberInput
          label="Limit"
          min={1}
          max={MAX_LIMIT}
          allowDecimal={false}
          value={form.limit}
          onChange={value => update({ limit: Number(value) || form.limit })}
        />
        <Group justify="space-between">
          <Button
            variant="subtle"
            onClick={() => {
              setForm(EMPTY_FORM);
              setSmartsText('');
            }}
          >
            Clear
          </Button>
          <Button onClick={() => onSearch({ ...form, reactionSmarts: lines(smartsText) })}>
            Search
          </Button>
        </Group>
      </Stack>
    );
  }
  ```

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes. Mantine renders `NumberInput` as a textbox, which is why the tests find
  the threshold and the limit by that role.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/search/SearchFormPanel.tsx \
    frontend/apps/viewer/src/search/SearchFormPanel.test.tsx
  git commit -m "Build the search form, with structures typed or drawn"
  ```

### Task F5.4: Selecting results

**Files:**

- Create: `frontend/apps/viewer/src/search/selection.ts`,
  `frontend/apps/viewer/src/search/selection.test.ts`
- Modify: `frontend/apps/viewer/src/components/ReactionList.tsx`,
  `frontend/apps/viewer/src/components/ReactionList.test.tsx`

**Interfaces:**

- Consumes: `REACTIONS_PER_REQUEST` (F2); `ReactionList` (F4.3).
- Produces:
  - `useSelection(key: string)` →
    `{selected: ReadonlyArray<string>, isSelected(id), canSelect(id), toggle(id), clear()}`,
    held in `sessionStorage` under `viewer-selection:<key>` and bounded at 100;
  - `ReactionList`'s optional `renderActions?: (record: ReactionRecord) => ReactNode`.

- [ ] **Step 1: Write the failing tests.** `src/search/selection.test.ts`:

  ```ts
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import { act, renderHook } from '@testing-library/react';
  import { useSelection } from '#search/selection.ts';

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  describe('useSelection', () => {
    it('selects and unselects, in the order chosen', () => {
      const { result } = renderHook(() => useSelection('limit=100'));
      act(() => result.current.toggle('b'));
      act(() => result.current.toggle('a'));
      expect(result.current.selected).toEqual(['b', 'a']);
      act(() => result.current.toggle('b'));
      expect(result.current.selected).toEqual(['a']);
      expect(result.current.isSelected('a')).toBe(true);
    });

    it('keeps the selection for its key across mounts', () => {
      const first = renderHook(() => useSelection('limit=100'));
      act(() => first.result.current.toggle('a'));
      first.unmount();
      expect(renderHook(() => useSelection('limit=100')).result.current.selected).toEqual(['a']);
      expect(renderHook(() => useSelection('limit=5')).result.current.selected).toEqual([]);
    });

    it('stops at 100', () => {
      const { result } = renderHook(() => useSelection('k'));
      for (let index = 0; index < 100; index += 1) {
        act(() => result.current.toggle(`ord-${index}`));
      }
      expect(result.current.canSelect('ord-100')).toBe(false);
      expect(result.current.canSelect('ord-1')).toBe(true);
      act(() => result.current.toggle('ord-100'));
      expect(result.current.selected).toHaveLength(100);
    });

    it('works without storage', () => {
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      const { result } = renderHook(() => useSelection('k'));
      act(() => result.current.toggle('a'));
      expect(result.current.selected).toEqual(['a']);
    });

    it('clears', () => {
      const { result } = renderHook(() => useSelection('k'));
      act(() => result.current.toggle('a'));
      act(() => result.current.clear());
      expect(result.current.selected).toEqual([]);
    });
  });
  ```

  In `src/components/ReactionList.test.tsx`, add:

  ```tsx
  it("puts each card's actions on it", async () => {
    mockApi({ 'GET /api/reactions': [VIEWER0101] });
    const { findByRole } = renderAt(
      '/',
      <ReactionList
        reactionIds={['ord-viewer0101']}
        renderActions={record => <button type="button">{`Pick ${record.reaction_id}`}</button>}
      />,
    );
    expect(await findByRole('button', { name: 'Pick ord-viewer0101' })).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run them to see them fail.**
  `npx vitest run src/search/selection.test.ts src/components/ReactionList.test.tsx`.
  Expected: FAIL, `Failed to resolve import "#search/selection.ts"`, and `renderActions`
  is not a prop.

- [ ] **Step 3: Write the hook, and the list's actions.** `src/search/selection.ts`:

  ```ts
  import { useCallback, useMemo, useState } from 'react';
  import { REACTIONS_PER_REQUEST } from '#api/hooks.ts';

  const PREFIX = 'viewer-selection:';

  function read(key: string): Array<string> {
    try {
      const stored = sessionStorage.getItem(PREFIX + key);
      const parsed: unknown = stored === null ? [] : JSON.parse(stored);
      return Array.isArray(parsed) ? parsed.filter(item => typeof item === 'string') : [];
    } catch {
      return [];
    }
  }

  function write(key: string, ids: ReadonlyArray<string>): void {
    try {
      sessionStorage.setItem(PREFIX + key, JSON.stringify(ids));
    } catch {
      // Storage can be full or blocked; the selection then lasts only as long as the page.
    }
  }

  /**
   * The reactions picked from one search's results, kept for the tab's session under the
   * search's URL, so Back returns to them. A set holds at most 100, one request's worth.
   */
  export function useSelection(key: string) {
    const [state, setState] = useState(() => ({ key, ids: read(key) }));
    // A new search reads its own selection.
    const ids = state.key === key ? state.ids : read(key);
    if (state.key !== key) {
      setState({ key, ids });
    }
    const save = useCallback(
      (next: Array<string>) => {
        write(key, next);
        setState({ key, ids: next });
      },
      [key],
    );
    return useMemo(
      () => ({
        selected: ids as ReadonlyArray<string>,
        isSelected: (id: string) => ids.includes(id),
        canSelect: (id: string) => ids.includes(id) || ids.length < REACTIONS_PER_REQUEST,
        toggle: (id: string) => {
          if (ids.includes(id)) {
            save(ids.filter(selected => selected !== id));
          } else if (ids.length < REACTIONS_PER_REQUEST) {
            save([...ids, id]);
          }
        },
        clear: () => save([]),
      }),
      [ids, save],
    );
  }
  ```

  In `src/components/ReactionList.tsx`, add to `ReactionListProps`:

  ```ts
  /** Controls for each card, such as a checkbox that selects it. */
  renderActions?: (record: ReactionRecord) => ReactNode;
  ```

  import `type ReactNode` from `react`, destructure `renderActions` in the component, and
  pass `actions={renderActions?.(record) ?? null}` to `ReactionCard`.

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/search/selection.ts frontend/apps/viewer/src/search/selection.test.ts \
    frontend/apps/viewer/src/components/ReactionList.tsx \
    frontend/apps/viewer/src/components/ReactionList.test.tsx
  git commit -m "Keep a search's selected reactions for the session, at most 100"
  ```

### Task F5.5: The search page, its results, and tables

**Files:**

- Create, under `frontend/apps/viewer/src/`: `components/ResultTable.tsx`,
  `components/ResultTable.test.tsx`, `components/ReactionResults.tsx`,
  `components/ReactionResults.test.tsx`, `pages/SearchPage.tsx`,
  `pages/SearchPage.test.tsx`
- Modify: `frontend/apps/viewer/src/routes.tsx`, `frontend/apps/viewer/src/routes.test.tsx`

**Interfaces:**

- Consumes: `formFromParams`, `paramsFromForm`, `compileQuery`, `SearchFormPanel`,
  `useSelection` (F5.1–F5.4); `useSearch` (F2); `ReactionList`, `DownloadButton`,
  `CopyLinkButton`, `ErrorNotice` (F4.3).
- Produces:
  - `ResultTable({result: TableResult})`;
  - `ReactionResults({result: ReactionsResult, selectionKey})`, which F6 reuses;
  - `SearchPage`, at `/search`.

- [ ] **Step 1: Write the failing tests.** `src/components/ResultTable.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { within } from '@testing-library/react';
  import { renderAt } from '#test/render.tsx';
  import { ResultTable } from '#components/ResultTable.tsx';

  describe('ResultTable', () => {
    it('shows the columns and rows as they come, linking reaction IDs', () => {
      const { getByRole } = renderAt(
        '/',
        <ResultTable
          result={{
            kind: 'table',
            columns: ['reaction_id', 'yield', 'note'],
            rows: [
              ['ord-viewer0101', 65, null],
              ['ord-viewer0102', 90.5, 'x'],
            ],
            truncated: false,
          }}
        />,
      );
      const table = getByRole('table');
      expect(
        within(table).getAllByRole('columnheader').map(cell => cell.textContent),
      ).toEqual(['reaction_id', 'yield', 'note']);
      expect(within(table).getByRole('link', { name: 'ord-viewer0102' })).toHaveAttribute(
        'href',
        '/reactions/ord-viewer0102',
      );
      expect(within(table).getByText('90.5')).toBeInTheDocument();
      expect(within(table).getByText('—')).toBeInTheDocument();
    });

    it('says when the rows were cut short', () => {
      const { getByText } = renderAt(
        '/',
        <ResultTable result={{ kind: 'table', columns: ['n'], rows: [[1]], truncated: true }} />,
      );
      expect(getByText(/stopped at 1,000 rows/)).toBeInTheDocument();
    });
  });
  ```

  `src/components/ReactionResults.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0101, VIEWER0102 } from '#test/fixtures/records.ts';
  import { ReactionResults } from '#components/ReactionResults.tsx';

  const RESULT = {
    kind: 'reactions' as const,
    reaction_ids: ['ord-viewer0101', 'ord-viewer0102'],
    truncated: false,
  };

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  describe('ReactionResults', () => {
    it('counts the reactions and lists them', async () => {
      mockApi({ 'GET /api/reactions': [VIEWER0101, VIEWER0102] });
      const { findByRole, getByRole } = renderAt(
        '/search',
        <ReactionResults result={RESULT} selectionKey="k" />,
      );
      expect(getByRole('heading', { name: '2 reactions' })).toBeInTheDocument();
      expect(await findByRole('link', { name: 'ord-viewer0102' })).toBeInTheDocument();
    });

    it('views the selected reactions as a set', async () => {
      mockApi({ 'GET /api/reactions': [VIEWER0101, VIEWER0102] });
      const user = userEvent.setup();
      const { findByRole, getByRole } = renderAt(
        '/search',
        <ReactionResults result={RESULT} selectionKey="k" />,
      );
      await user.click(await findByRole('checkbox', { name: 'Select ord-viewer0102' }));
      await user.click(getByRole('checkbox', { name: 'Select ord-viewer0101' }));
      expect(getByRole('link', { name: 'View 2 selected' })).toHaveAttribute(
        'href',
        '/reactions?id=ord-viewer0102&id=ord-viewer0101',
      );
    });

    it('says when the reactions were cut short', () => {
      mockApi({ 'GET /api/reactions': [] });
      const { getByText } = renderAt(
        '/search',
        <ReactionResults result={{ ...RESULT, truncated: true }} selectionKey="k" />,
      );
      expect(getByText(/stopped at 1,000 reactions/)).toBeInTheDocument();
    });
  });
  ```

  `src/pages/SearchPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0103 } from '#test/fixtures/records.ts';
  import { SearchPage } from '#pages/SearchPage.tsx';

  vi.mock('@open-reaction-database/ui/ketcher', () => ({ StructureDialog: () => null }));

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  describe('SearchPage', () => {
    it('asks for criteria before searching', () => {
      const fetch = mockApi({});
      const { getByText } = renderAt('/search', <SearchPage />);
      expect(getByText('Set a structure, a reaction SMARTS, a range, or an ID, then search.')).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
    });

    it("runs the URL's search and shows its reactions", async () => {
      const fetch = mockApi({
        'POST /api/search': { kind: 'reactions', reaction_ids: ['ord-viewer0103'], truncated: false },
        'GET /api/reactions': [VIEWER0103],
      });
      const { findByRole } = renderAt('/search?reaction_id=ord-viewer0103&limit=100', <SearchPage />);
      expect(await findByRole('link', { name: 'ord-viewer0103' })).toBeInTheDocument();
      const body = JSON.parse(String(fetch.mock.calls[0][1]?.body));
      expect(body.query.where.clauses[0].value.literal).toBe('ord-viewer0103');
    });

    it('puts a new search in the URL', async () => {
      mockApi({});
      const user = userEvent.setup();
      const { getByRole, history } = renderAt('/search', <SearchPage />);
      await user.click(getByRole('button', { name: 'Add a structure' }));
      await user.type(getByRole('textbox', { name: 'Structure 1' }), 'CCN');
      await user.click(getByRole('button', { name: 'Search' }));
      const params = new URLSearchParams(history.at(-1)!.split('?')[1]);
      expect(JSON.parse(params.get('component')!)).toEqual({
        pattern: 'CCN',
        target: 'input',
        mode: 'exact',
      });
    });

    it("shows the server's reason for a search it refused", async () => {
      mockApi({
        'POST /api/search': () =>
          new Response(JSON.stringify({ detail: 'cannot parse SMARTS "C(("' }), { status: 422 }),
      });
      const { findByRole } = renderAt(
        `/search?component=${encodeURIComponent('C((;input;smarts')}&limit=100`,
        <SearchPage />,
      );
      expect(await findByRole('alert')).toHaveTextContent('cannot parse SMARTS');
    });

    it('notes where answers differ from the old site', () => {
      const { getByText } = renderAt('/search', <SearchPage />);
      expect(getByText(/returns fewer reactions than the old site/)).toBeInTheDocument();
    });
  });
  ```

  `VIEWER0103` is not in F4.1's fixture module; add `'ord-viewer0103'` to
  `REACTION_IDS` in `scripts/fixture-records.py`, regenerate the module as F4.1's Step 1
  does, and check that only the new export changed.

  In `src/routes.test.tsx`, add:

  ```tsx
  it('shows the search at /search', () => {
    const { getByRole } = renderAt('/search', <ViewerRoutes />);
    expect(getByRole('button', { name: 'Search' })).toBeInTheDocument();
  });
  ```

  and mock `@open-reaction-database/ui/ketcher` as `SearchPage.test.tsx` does.

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/components/ResultTable.test.tsx \
    src/components/ReactionResults.test.tsx src/pages/SearchPage.test.tsx src/routes.test.tsx
  ```

  Expected: FAIL, with `Failed to resolve import` for the new modules, and `/search`
  showing NotFound.

- [ ] **Step 3: Write the table, the results, and the page.**
  `src/components/ResultTable.tsx`:

  ```tsx
  import { Alert, Anchor, ScrollArea, Stack, Table } from '@mantine/core';
  import { Link } from 'wouter';
  import type { TableResult } from '#api/types.ts';

  function Cell({ column, value }: Readonly<{ column: string; value: unknown }>) {
    if (value === null || value === undefined) {
      return <>—</>;
    }
    if (column === 'reaction_id' && typeof value === 'string') {
      return (
        <Anchor
          component={Link}
          href={`/reactions/${encodeURIComponent(value)}`}
        >
          {value}
        </Anchor>
      );
    }
    return <>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</>;
  }

  /** A table result's columns and rows as they come, with reaction IDs linked. */
  export function ResultTable({ result }: Readonly<{ result: TableResult }>) {
    return (
      <Stack gap="sm">
        {result.truncated && (
          <Alert
            color="yellow"
            variant="light"
          >
            The answer stopped at 1,000 rows; narrow the question to see the rest.
          </Alert>
        )}
        <ScrollArea>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                {result.columns.map(column => (
                  <Table.Th key={column}>{column}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {result.rows.map((row, rowIndex) => (
                // Rows have no identity of their own; their place is stable for a result.
                <Table.Tr key={rowIndex}>
                  {result.columns.map((column, columnIndex) => (
                    <Table.Td key={column}>
                      <Cell
                        column={column}
                        value={row[columnIndex]}
                      />
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Stack>
    );
  }
  ```

  `src/components/ReactionResults.tsx`:

  ```tsx
  import { Alert, Button, Checkbox, Group, Stack, Title } from '@mantine/core';
  import { Link } from 'wouter';
  import type { ReactionsResult } from '#api/types.ts';
  import { CopyLinkButton } from '#components/CopyLinkButton.tsx';
  import { DownloadButton } from '#components/DownloadButton.tsx';
  import { ReactionList } from '#components/ReactionList.tsx';
  import { useSelection } from '#search/selection.ts';

  interface ReactionResultsProps {
    result: ReactionsResult;
    /** Names the selection kept for these results, such as the page's URL. */
    selectionKey: string;
  }

  /** A search's reactions: counted, selectable, downloadable, and listed. */
  export function ReactionResults({ result, selectionKey }: Readonly<ReactionResultsProps>) {
    const selection = useSelection(selectionKey);
    const count = result.reaction_ids.length;
    const setPath = `/reactions?${new URLSearchParams(
      selection.selected.map(id => ['id', id]),
    )}`;
    return (
      <Stack gap="md">
        <Group
          justify="space-between"
          wrap="wrap"
        >
          <Title order={3}>
            {count.toLocaleString()} {count === 1 ? 'reaction' : 'reactions'}
          </Title>
          <Group gap="sm">
            <Button
              component={Link}
              href={setPath}
              disabled={selection.selected.length === 0}
            >
              View {selection.selected.length} selected
            </Button>
            <Button
              variant="subtle"
              onClick={selection.clear}
              disabled={selection.selected.length === 0}
            >
              Clear selection
            </Button>
            <CopyLinkButton />
            <DownloadButton reactionIds={result.reaction_ids}>Download all</DownloadButton>
          </Group>
        </Group>
        {result.truncated && (
          <Alert
            color="yellow"
            variant="light"
          >
            The search stopped at 1,000 reactions; narrow it to see the rest.
          </Alert>
        )}
        <ReactionList
          reactionIds={result.reaction_ids}
          renderActions={record => {
            const id = record.reaction_id;
            const blocked = !selection.canSelect(id);
            return (
              <Checkbox
                aria-label={`Select ${id}`}
                title={blocked ? 'A set holds at most 100 reactions.' : undefined}
                checked={selection.isSelected(id)}
                disabled={blocked}
                onChange={() => selection.toggle(id)}
              />
            );
          }}
        />
      </Stack>
    );
  }
  ```

  A disabled `Button` rendered as a link still carries its `href`; Mantine sets
  `data-disabled` and blocks pointer events, which the test's enabled case does not
  exercise. If the review wants the disabled link gone from the tab order, render a
  plain disabled `Button` when nothing is selected.

  `src/pages/SearchPage.tsx`:

  ```tsx
  import { Alert, Button, Flex, Loader, Paper, Stack, Text, Title } from '@mantine/core';
  import { useMemo, useState } from 'react';
  import { useLocation, useSearchParams } from 'wouter';
  import { useSearch } from '#api/hooks.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { ReactionResults } from '#components/ReactionResults.tsx';
  import { ResultTable } from '#components/ResultTable.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';
  import { compileQuery } from '#search/compile.ts';
  import { formFromParams, paramsFromForm } from '#search/form.ts';
  import { SearchFormPanel } from '#search/SearchFormPanel.tsx';

  function HelpNote() {
    return (
      <Alert
        variant="light"
        title="Where answers differ from the old site"
      >
        A reaction SMARTS with several templates on one side returns fewer reactions than the
        old site, since each template has to match a molecule of its own. A substructure
        typed as SMILES is read as SMARTS, which matches the same molecules for most
        patterns but not, for example, a charged or explicit-hydrogen atom. The dataset
        charts count the SMILES the corpus records.
      </Alert>
    );
  }

  /** The search form beside its results; the URL holds the form, so a search can be linked. */
  export function SearchPage() {
    const [searchParams] = useSearchParams();
    const [, navigate] = useLocation();
    const search = searchParams.toString();
    const form = useMemo(() => formFromParams(new URLSearchParams(search)), [search]);
    const query = useMemo(() => compileQuery(form), [form]);
    const results = useSearch(query);
    const [showForm, setShowForm] = useState(true);
    let body;
    if (query === null) {
      body = <Text>Set a structure, a reaction SMARTS, a range, or an ID, then search.</Text>;
    } else if (results.isError) {
      body = <ErrorNotice error={results.error} />;
    } else if (results.isPending) {
      body = (
        <Flex justify="center">
          <Loader />
        </Flex>
      );
    } else if (results.data.kind === 'reactions') {
      body = (
        <ReactionResults
          result={results.data}
          selectionKey={search}
        />
      );
    } else {
      body = <ResultTable result={results.data} />;
    }
    return (
      <ViewerPage breadcrumbs={[{ title: 'Search', path: search ? `/search?${search}` : '/search' }]}>
        <Stack gap="md">
          <Flex
            justify="space-between"
            align="center"
          >
            <Title order={2}>Search</Title>
            <Button
              variant="default"
              onClick={() => setShowForm(shown => !shown)}
            >
              {showForm ? 'Hide the form' : 'Show the form'}
            </Button>
          </Flex>
          <Flex
            direction={{ base: 'column', md: 'row' }}
            gap="lg"
            align="flex-start"
          >
            {showForm && (
              <Paper
                p="md"
                withBorder
                w={{ base: '100%', md: 360 }}
              >
                <Stack gap="md">
                  <SearchFormPanel
                    // A new URL, such as Back to an earlier search, starts the form afresh.
                    key={search}
                    initial={form}
                    onSearch={next => navigate(`/search?${paramsFromForm(next)}`)}
                  />
                  <HelpNote />
                </Stack>
              </Paper>
            )}
            <Stack
              gap="md"
              style={{ flex: 1, minWidth: 0 }}
            >
              {body}
            </Stack>
          </Flex>
        </Stack>
      </ViewerPage>
    );
  }
  ```

  In `src/routes.tsx`, import `SearchPage` and add, after the reaction routes:

  ```tsx
  <Route
    path="/search"
    component={SearchPage}
  />
  ```

- [ ] **Step 4: Run the whole suite**, then the type check. Expected: every test passes,
  and `tsc -b` is clean.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/scripts/fixture-records.py frontend/apps/viewer/src/test/fixtures \
    frontend/apps/viewer/src/components frontend/apps/viewer/src/pages/SearchPage.tsx \
    frontend/apps/viewer/src/pages/SearchPage.test.tsx frontend/apps/viewer/src/routes.tsx \
    frontend/apps/viewer/src/routes.test.tsx
  git commit -m "Search from the form, with selectable results, tables, and a help note"
  ```

### Task F5.6: One search per field, end to end, and the PR

**Files:**

- Create: `frontend/apps/viewer/e2e/search.spec.ts`
- Modify: `frontend/apps/viewer/vite.config.ts` (floors), `CLAUDE.md`

- [ ] **Step 1: The specs.** `e2e/search.spec.ts`. Each case is the check `tsc` cannot
  make: that the compiled paths and operators run against the backend, over the fixture
  corpus. The expected IDs are what F4–F6's planning measured with these queries:

  ```ts
  import { expect, test, type Page } from '@playwright/test';

  const REACTION_LINK = /^ord-viewer\d{4}$/;

  function component(pattern: string, target: string, mode: string): [string, string] {
    return ['component', JSON.stringify({ pattern, target, mode })];
  }

  async function expectResults(page: Page, params: Array<[string, string]>, ids: Array<string>) {
    await page.goto(`/search?${new URLSearchParams([...params, ['limit', '100']])}`);
    if (ids.length === 0) {
      await expect(page.getByText('No reactions.')).toBeVisible();
    } else {
      await expect(page.getByRole('link', { name: REACTION_LINK })).toHaveText(ids);
    }
  }

  test.describe('each field searches the corpus', () => {
    test('an exact input', async ({ page }) => {
      await expectResults(page, [component('CC(=O)Cl', 'input', 'exact')], [
        'ord-viewer0102',
        'ord-viewer0103',
        'ord-viewer0201',
      ]);
    });

    test('a similar input', async ({ page }) => {
      await expectResults(page, [component('CCN', 'input', 'similar'), ['similarity', '0.5']], [
        'ord-viewer0103',
      ]);
    });

    test('a substructure input', async ({ page }) => {
      await expectResults(page, [component('C(=O)Cl', 'input', 'substructure')], [
        'ord-viewer0102',
        'ord-viewer0103',
        'ord-viewer0201',
      ]);
    });

    test('a SMARTS product, with and without stereochemistry', async ({ page }) => {
      const smarts = component('C[C@@H](N)C(=O)O', 'output', 'smarts');
      await expectResults(page, [smarts, ['use_stereochemistry', 'true']], ['ord-viewer0102']);
      await expectResults(page, [smarts, ['use_stereochemistry', 'false']], [
        'ord-viewer0102',
        'ord-viewer0201',
      ]);
    });

    test('a reaction SMARTS', async ({ page }) => {
      await expectResults(page, [['reaction_smarts', '[NX3:1].[CX3:2](=O)Cl>>[N:1][C:2]=O']], [
        'ord-viewer0102',
        'ord-viewer0103',
        'ord-viewer0201',
      ]);
    });

    test('a yield range', async ({ page }) => {
      await expectResults(page, [['min_yield', '70'], ['max_yield', '100']], [
        'ord-viewer0102',
        'ord-viewer0103',
      ]);
    });

    test('a conversion range', async ({ page }) => {
      await expectResults(page, [['min_conversion', '0'], ['max_conversion', '50']], []);
    });

    test('a dataset ID', async ({ page }) => {
      await expectResults(page, [['dataset_id', 'ord_dataset-viewer02']], [
        'ord-viewer0201',
        'ord-viewer0202',
      ]);
    });

    test('a DOI', async ({ page }) => {
      await expectResults(page, [['doi', '10.1/x']], []);
    });

    test('a reaction ID', async ({ page }) => {
      await expectResults(page, [['reaction_id', 'ord-viewer0103']], ['ord-viewer0103']);
    });

    test("ord-interface's legacy component", async ({ page }) => {
      await expectResults(page, [['component', 'CC(=O)Cl;input;exact']], [
        'ord-viewer0102',
        'ord-viewer0103',
        'ord-viewer0201',
      ]);
    });
  });

  test('searches from the form, and keeps a selection across Back', async ({ page }) => {
    await page.goto('/search');
    await page.getByRole('button', { name: 'Add a structure' }).click();
    await page.getByRole('textbox', { name: 'Structure 1' }).fill('CC(=O)Cl');
    await page.getByRole('button', { name: 'Search' }).click();
    await expect(page.getByRole('link', { name: REACTION_LINK })).toHaveCount(3);
    await page.getByRole('checkbox', { name: 'Select ord-viewer0103' }).check();
    await page.getByRole('link', { name: 'View 1 selected' }).click();
    await expect(page).toHaveURL('/reactions?id=ord-viewer0103');
    await page.goBack();
    await expect(page.getByRole('checkbox', { name: 'Select ord-viewer0103' })).toBeChecked();
  });

  test('opens the drawing dialog', async ({ page }) => {
    await page.goto('/search');
    await page.getByRole('button', { name: 'Add a structure' }).click();
    await page.getByRole('button', { name: 'Draw structure 1' }).click();
    await expect(page.locator('.Ketcher-root')).toBeVisible({ timeout: 30_000 });
  });
  ```

  Run the specs locally as F4.8's Step 5 does. Expected: every spec passes.

- [ ] **Step 2: Floors and docs.** Raise the coverage floors to the measured values. In
  `CLAUDE.md`'s `apps/viewer/` bullet, add `search/`: the form's URL state, its compiler
  to a `Query`, and the selection.
- [ ] **Step 3: Open the PR.** Title "Search the corpus in the viewer". Run the checks,
  open it, bind it, turn on auto-fix, and run `review-pr`.

---

## PR F6: `/ask`

Branch `viewer-ask`, in its own worktree from `origin/main` once F5 has merged.

### Task F6.1: A scripted model client for the end-to-end backend

**Files:**

- Modify: `backend/viewer/ord_viewer/testing.py`,
  `backend/viewer/ord_viewer/testing_test.py`,
  `backend/viewer/ord_viewer/routes/ask_test.py`

**Interfaces:**

- Produces, in `ord_viewer.testing`:
  - `DECLINED`, and `StubAskClient(*responses)`, the ask tests' `_StubClient` moved here
    unchanged in behavior;
  - `ScriptedAskClient(scripts)`, which answers each scripted question and declines any
    other;
  - `ASK_SCRIPTS`, the end-to-end questions;
  - `e2e_app`, now with a `ScriptedAskClient` over `ASK_SCRIPTS`.

The ask route's model calls are two, and each request says which it is: the query call
carries `tools`, and its first message is the question; the answer call carries none, and
its message starts `Question: <the question>`, then `Result:`. F4–F6's planning read
both in ord-schema 0.9.2's `nl`.

- [ ] **Step 1: Write the failing tests.** In `testing_test.py`, import `ASK_SCRIPTS`,
  `ScriptedAskClient` from `ord_viewer.testing`, replace
  `test_e2e_app_has_no_model_client` with:

  ```python
  def test_e2e_app_answers_its_scripted_questions(tmp_path, monkeypatch):
      derive_corpus(tmp_path)
      monkeypatch.setenv("ORD_VIEWER_CORPUS_DIR", str(tmp_path))
      with TestClient(e2e_app()) as client:
          response = client.post(
              "/api/ask", json={"question": "reactions that use acetyl chloride"}
          )
          assert response.status_code == 200, response.text
          body = response.json()
          assert body["text"] == "Three reactions use acetyl chloride."
          assert body["result"]["reaction_ids"] == [
              "ord-viewer0102",
              "ord-viewer0103",
              "ord-viewer0201",
          ]
          table = client.post(
              "/api/ask", json={"question": "how many reactions are in each dataset"}
          )
          assert table.json()["result"] == {
              "kind": "table",
              "columns": ["dataset_id", "reactions"],
              "rows": [["ord_dataset-viewer01", 3], ["ord_dataset-viewer02", 2]],
              "truncated": False,
          }


  def test_e2e_app_cannot_answer_other_questions(tmp_path, monkeypatch):
      derive_corpus(tmp_path)
      monkeypatch.setenv("ORD_VIEWER_CORPUS_DIR", str(tmp_path))
      with TestClient(e2e_app()) as client:
          response = client.post("/api/ask", json={"question": "what does pyridine cost"})
          assert response.status_code == 422
          assert "no script" in response.json()["detail"]


  def test_scripted_client_answers_from_the_question_in_each_request():
      client = ScriptedAskClient({"q": ({"limit": 1}, "an answer")})
      query_call = client.create(tools=[], messages=[{"role": "user", "content": "q"}])
      assert query_call.content[0].input == {"limit": 1}
      answer_call = client.create(
          messages=[{"role": "user", "content": "Question: q\n\nResult:\nrows"}]
      )
      assert answer_call.content[0].text == "an answer"


  def test_every_script_compiles(tmp_path):
      derive_corpus(tmp_path)
      with make_client(tmp_path) as client:
          for query, _ in ASK_SCRIPTS.values():
              response = client.post("/api/search", json={"query": query})
              assert response.status_code == 200, (query, response.text)
  ```

  In `routes/ask_test.py`, delete `_DECLINED` and `_StubClient`, import `DECLINED` and
  `StubAskClient` from `ord_viewer.testing`, and replace each use (`_DECLINED` with
  `DECLINED`, `_StubClient(` with `StubAskClient(`, and the fixture's return type).

  Run `uv run pytest ord_viewer/testing_test.py ord_viewer/routes/ask_test.py -q` from
  `backend/viewer`. Expected: FAIL, `ImportError: cannot import name 'ASK_SCRIPTS'`.

- [ ] **Step 2: Move the stub, and write the scripted client.** In `ord_viewer/testing.py`,
  add `import types`, `from collections.abc import Mapping`, and
  `from anthropic.types import TextBlock, ToolUseBlock` to the imports, and:

  ```python
  # A response the model's safety classifiers stopped.
  DECLINED = "declined"


  def _message(payload: Any) -> types.SimpleNamespace:
      """Build a Messages API response from a scripted payload.

      Args:
          payload: A dict holding "reason" for a cannot_answer call, any other dict for a
              build_query call, DECLINED for a classifier's stop, or another string for
              the answer's prose.

      Returns:
          A message with that content and nominal usage.
      """
      usage = types.SimpleNamespace(
          input_tokens=1,
          output_tokens=1,
          cache_creation_input_tokens=0,
          cache_read_input_tokens=0,
      )
      if payload == DECLINED:
          details = types.SimpleNamespace(category="cyber")
          return types.SimpleNamespace(
              content=[], usage=usage, stop_reason="refusal", stop_details=details
          )
      if isinstance(payload, str):
          content: list[Any] = [TextBlock(type="text", text=payload)]
      else:
          tool = "cannot_answer" if "reason" in payload else "build_query"
          content = [
              ToolUseBlock(type="tool_use", id="toolu_stub", name=tool, input=payload)
          ]
      stop = "end_turn" if isinstance(payload, str) else "tool_use"
      return types.SimpleNamespace(content=content, usage=usage, stop_reason=stop)


  class StubAskClient:
      """Answers messages.create from a script, in order: a query, prose, or a refusal.

      Args:
          *responses: One per call, in order, as _message reads them; an exception is
              raised instead.
      """

      def __init__(self, *responses: Any) -> None:
          self._responses = list(responses)
          self.requests: list[dict[str, Any]] = []
          self.messages = self
          self.closed = False

      def close(self) -> None:
          """Record that the app closed the client, as it does at shutdown."""
          self.closed = True

      def create(self, **kwargs: Any) -> types.SimpleNamespace:
          """Record the request and answer with the next scripted response.

          Args:
              **kwargs: The request nl.ask sends.

          Returns:
              The next scripted message.

          Raises:
              Exception: The next scripted response, when it is one.
          """
          self.requests.append(kwargs)
          payload = self._responses.pop(0)
          if isinstance(payload, Exception):
              raise payload
          return _message(payload)


  def _text_of(message: Mapping[str, Any]) -> str:
      """Return a message's text, whether its content is a string or blocks."""
      content = message["content"]
      if isinstance(content, str):
          return content
      return "".join(block.get("text", "") for block in content)


  class ScriptedAskClient:
      """Answers each question it has a script for, and cannot answer any other.

      nl.ask makes two calls a question. The query call carries tools, and its first
      message is the question; the answer call carries none, and its message starts
      "Question: <question>" before the result.

      Args:
          scripts: For each question, the query it compiles to and the sentence that
              answers it.
      """

      def __init__(self, scripts: Mapping[str, tuple[dict[str, Any], str]]) -> None:
          self._scripts = scripts
          self.messages = self

      def close(self) -> None:
          """Nothing to release; the app closes its client at shutdown."""

      def create(self, **kwargs: Any) -> types.SimpleNamespace:
          """Answer the question in the request from its script.

          Args:
              **kwargs: The request nl.ask sends.

          Returns:
              The scripted query, the scripted sentence, or a cannot_answer call.
          """
          text = _text_of(kwargs["messages"][0])
          if "tools" in kwargs:
              script = self._scripts.get(text)
              if script is None:
                  return _message({"reason": "the scripted client has no script for it"})
              return _message(script[0])
          question = text.removeprefix("Question: ").split("\n\nResult:", 1)[0]
          return _message(self._scripts[question][1])


  # The questions the viewer's end-to-end tests ask, over the fixture corpus.
  ASK_SCRIPTS: dict[str, tuple[dict[str, Any], str]] = {
      "reactions that use acetyl chloride": (
          {
              "where": {
                  "op": "exists",
                  "path": "inputs.components",
                  "where": {"op": "same_compound", "path": "smiles", "smiles": "CC(=O)Cl"},
              }
          },
          "Three reactions use acetyl chloride.",
      ),
      "how many reactions are in each dataset": (
          {
              "aggregate": {
                  "group_by": ["dataset_id"],
                  "measures": [{"fn": "count", "name": "reactions"}],
              },
              "order_by": [{"key": "dataset_id"}],
          },
          "The first dataset holds three reactions, and the second two.",
      ),
  }
  ```

  and change `e2e_app` to give the app the scripted client, with its docstring saying
  so:

  ```python
  def e2e_app() -> FastAPI:
      """Build the app the viewer's end-to-end tests run against.

      Reads ORD_VIEWER_CORPUS_DIR and the other settings from the environment, as the
      image does, resolves compound names from COMPOUND_NAMES without the network, and
      answers /api/ask from ASK_SCRIPTS.

      Returns:
          The app, for ``uvicorn --factory ord_viewer.testing:e2e_app``.
      """
      return create_app(
          resolver=offline_resolver,
          ask_client_factory=lambda: ScriptedAskClient(ASK_SCRIPTS),
      )
  ```

  `create_app`'s `ask_client_factory` is typed to return `anthropic.Anthropic | None`;
  `ty` will reject the scripted client there. Cast it,
  `cast(anthropic.Anthropic, ScriptedAskClient(ASK_SCRIPTS))`, with a comment that the
  client answers the one method the route calls, and import `anthropic`.

- [ ] **Step 3: Run the suite.** `uv run pytest -n auto -q`, then
  `uv run ruff check ord_viewer && uv run ruff format --check ord_viewer && uv run ty check ord_viewer`.
  Expected: every test passes, the ask tests among them on the moved stub, and the
  checks are clean.

- [ ] **Step 4: Commit.**

  ```bash
  git add backend/viewer/ord_viewer/testing.py backend/viewer/ord_viewer/testing_test.py \
    backend/viewer/ord_viewer/routes/ask_test.py
  git commit -m "Answer scripted questions in the viewer's end-to-end backend"
  ```

### Task F6.2: The ask page

**Files:**

- Create: `frontend/apps/viewer/src/pages/AskPage.tsx`,
  `frontend/apps/viewer/src/pages/AskPage.test.tsx`
- Modify: `frontend/apps/viewer/src/routes.tsx`, `frontend/apps/viewer/src/routes.test.tsx`

**Interfaces:**

- Consumes: `useAsk` (F2); `ReactionResults`, `ResultTable`, `ErrorNotice` (F4.3, F5.5).
- Produces: `MAX_QUESTION = 2000`, `ASK_EXAMPLES`, and `AskPage` at `/ask?q=…`, not
  linked from the navigation.

- [ ] **Step 1: Write the failing tests.** `src/pages/AskPage.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import userEvent from '@testing-library/user-event';
  import { renderAt } from '#test/render.tsx';
  import { mockApi } from '#test/fetch.ts';
  import { VIEWER0103 } from '#test/fixtures/records.ts';
  import { ASK_EXAMPLES, AskPage } from '#pages/AskPage.tsx';

  const QUESTION = 'reactions that use ethylamine';
  const ANSWER = {
    query: { where: { op: 'eq', path: 'reaction_id', value: { literal: 'ord-viewer0103' } } },
    text: 'One reaction uses ethylamine.',
    result: { kind: 'reactions', reaction_ids: ['ord-viewer0103'], truncated: false },
  };

  afterEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  describe('AskPage', () => {
    it('says the feature is in development', () => {
      const { getByText } = renderAt('/ask', <AskPage />);
      expect(getByText(/in development/)).toBeInTheDocument();
    });

    it("asks the URL's question and shows the answer", async () => {
      const fetch = mockApi({ 'POST /api/ask': ANSWER, 'GET /api/reactions': [VIEWER0103] });
      const { findByText, findByRole } = renderAt(
        `/ask?q=${encodeURIComponent(QUESTION)}`,
        <AskPage />,
      );
      expect(await findByText('One reaction uses ethylamine.')).toBeInTheDocument();
      expect(await findByRole('link', { name: 'ord-viewer0103' })).toBeInTheDocument();
      expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ question: QUESTION });
    });

    it('shows the query the question compiled to, folded away', async () => {
      const user = userEvent.setup();
      mockApi({ 'POST /api/ask': ANSWER, 'GET /api/reactions': [VIEWER0103] });
      const { findByRole } = renderAt(`/ask?q=${encodeURIComponent(QUESTION)}`, <AskPage />);
      const toggle = await findByRole('button', { name: 'The query it ran' });
      await user.click(toggle);
      expect(await findByRole('region', { name: 'The query it ran' })).toHaveTextContent(
        '"literal": "ord-viewer0103"',
      );
    });

    it('shows a table answer as a table', async () => {
      mockApi({
        'POST /api/ask': {
          ...ANSWER,
          result: { kind: 'table', columns: ['n'], rows: [[5]], truncated: false },
        },
      });
      const { findByRole } = renderAt(`/ask?q=${encodeURIComponent(QUESTION)}`, <AskPage />);
      expect(await findByRole('table')).toHaveTextContent('5');
    });

    it('puts a typed question in the URL', async () => {
      mockApi({});
      const user = userEvent.setup();
      const { getByRole, history } = renderAt('/ask', <AskPage />);
      await user.type(getByRole('textbox', { name: 'Question' }), QUESTION);
      await user.click(getByRole('button', { name: 'Ask' }));
      expect(new URLSearchParams(history.at(-1)!.split('?')[1]).get('q')).toBe(QUESTION);
    });

    it('asks an example', async () => {
      mockApi({});
      const user = userEvent.setup();
      const { getByRole, history } = renderAt('/ask', <AskPage />);
      await user.click(getByRole('button', { name: ASK_EXAMPLES[0] }));
      expect(new URLSearchParams(history.at(-1)!.split('?')[1]).get('q')).toBe(ASK_EXAMPLES[0]);
    });

    it('refuses an empty or overlong question', async () => {
      const user = userEvent.setup();
      const { getByRole } = renderAt('/ask', <AskPage />);
      expect(getByRole('button', { name: 'Ask' })).toBeDisabled();
      await user.click(getByRole('textbox', { name: 'Question' }));
      await user.paste('x'.repeat(2001));
      expect(getByRole('button', { name: 'Ask' })).toBeDisabled();
    });

    it("shows the server's reason for a question it cannot answer", async () => {
      mockApi({
        'POST /api/ask': () =>
          new Response(JSON.stringify({ detail: 'the corpus records no prices' }), {
            status: 422,
          }),
      });
      const { findByRole } = renderAt('/ask?q=what%20does%20it%20cost', <AskPage />);
      expect(await findByRole('alert')).toHaveTextContent('the corpus records no prices');
    });
  });
  ```

  In `src/routes.test.tsx`, add:

  ```tsx
  it('shows /ask without listing it in the navigation', () => {
    const { getByRole, queryByRole } = renderAt('/ask', <ViewerRoutes />);
    expect(getByRole('heading', { name: 'Ask about reactions' })).toBeInTheDocument();
    expect(queryByRole('link', { name: /ask/i })).not.toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run them to see them fail.**
  `npx vitest run src/pages/AskPage.test.tsx src/routes.test.tsx`. Expected: FAIL,
  `Failed to resolve import "#pages/AskPage.tsx"`, and `/ask` showing NotFound.

- [ ] **Step 3: Write the page.** `src/pages/AskPage.tsx`:

  ```tsx
  import {
    Accordion,
    Alert,
    Button,
    Code,
    Flex,
    Group,
    Loader,
    Stack,
    Text,
    Textarea,
    Title,
  } from '@mantine/core';
  import { useState } from 'react';
  import { useLocation, useSearchParams } from 'wouter';
  import { useAsk } from '#api/hooks.ts';
  import type { AskResponse } from '#api/types.ts';
  import { ErrorNotice } from '#components/ErrorNotice.tsx';
  import { ReactionResults } from '#components/ReactionResults.tsx';
  import { ResultTable } from '#components/ResultTable.tsx';
  import { ViewerPage } from '#components/ViewerPage.tsx';

  /** The backend's bound on a question's length. */
  export const MAX_QUESTION = 2000;

  /** ord-interface's examples. */
  export const ASK_EXAMPLES = [
    'reactions for synthesizing ibuprofen',
    'reactions using benzene as an input with yield greater than 70%',
    'reactions that make an aryl boronic acid',
  ];

  function Answer({ answer, selectionKey }: Readonly<{ answer: AskResponse; selectionKey: string }>) {
    return (
      <Stack gap="md">
        <Text>{answer.text}</Text>
        <Accordion variant="contained">
          <Accordion.Item value="query">
            <Accordion.Control>The query it ran</Accordion.Control>
            <Accordion.Panel>
              <Code block>{JSON.stringify(answer.query, null, 2)}</Code>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
        {answer.result.kind === 'reactions' ? (
          <ReactionResults
            result={answer.result}
            selectionKey={selectionKey}
          />
        ) : (
          <ResultTable result={answer.result} />
        )}
      </Stack>
    );
  }

  /** Ask a question in English; the backend compiles it to a query and answers it. */
  export function AskPage() {
    const [searchParams] = useSearchParams();
    const [, navigate] = useLocation();
    const question = searchParams.get('q') ?? '';
    const [draft, setDraft] = useState(question);
    const answer = useAsk(question === '' ? null : question);
    const ask = (text: string) => navigate(`/ask?${new URLSearchParams({ q: text })}`);
    const trimmed = draft.trim();
    let body = null;
    if (question !== '') {
      if (answer.isError) {
        body = <ErrorNotice error={answer.error} />;
      } else if (answer.isPending) {
        body = (
          <Flex justify="center">
            <Loader />
          </Flex>
        );
      } else {
        body = (
          <Answer
            answer={answer.data}
            selectionKey={`ask:${question}`}
          />
        );
      }
    }
    return (
      <ViewerPage breadcrumbs={[{ title: 'Ask', path: '/ask' }]}>
        <Stack gap="md">
          <Alert
            color="yellow"
            variant="light"
          >
            This feature is in development — results may be incomplete or change.
          </Alert>
          <Title order={2}>Ask about reactions</Title>
          <Textarea
            label="Question"
            placeholder="e.g. reactions using benzene as an input with yield greater than 70%"
            autosize
            minRows={2}
            value={draft}
            error={draft.length > MAX_QUESTION ? `At most ${MAX_QUESTION} characters.` : null}
            onChange={event => setDraft(event.currentTarget.value)}
          />
          <Group justify="space-between">
            <Group gap="xs">
              {ASK_EXAMPLES.map(example => (
                <Button
                  key={example}
                  variant="light"
                  size="xs"
                  onClick={() => {
                    setDraft(example);
                    ask(example);
                  }}
                >
                  {example}
                </Button>
              ))}
            </Group>
            <Button
              disabled={trimmed === '' || draft.length > MAX_QUESTION}
              onClick={() => ask(trimmed)}
            >
              Ask
            </Button>
          </Group>
          {body}
        </Stack>
      </ViewerPage>
    );
  }
  ```

  In `src/routes.tsx`, import `AskPage` and add
  `<Route path="/ask" component={AskPage} />` after `/search`.

- [ ] **Step 4: Run the tests to see them pass.** Same command as Step 2. Expected: every
  test passes. Mantine's `Accordion.Control` is a button named by its text, and its
  panel a region labelled by the control.

- [ ] **Step 5: Commit.**

  ```bash
  git add frontend/apps/viewer/src/pages/AskPage.tsx frontend/apps/viewer/src/pages/AskPage.test.tsx \
    frontend/apps/viewer/src/routes.tsx frontend/apps/viewer/src/routes.test.tsx
  git commit -m "Ask about reactions in English, under a banner that says it is in development"
  ```

### Task F6.3: The ask flow end to end, and the PR

**Files:**

- Create: `frontend/apps/viewer/e2e/ask.spec.ts`
- Modify: `frontend/apps/viewer/vite.config.ts` (floors), `CLAUDE.md`

- [ ] **Step 1: The spec.** `e2e/ask.spec.ts`, against `ASK_SCRIPTS`:

  ```ts
  import { expect, test } from '@playwright/test';

  const REACTION_LINK = /^ord-viewer\d{4}$/;

  test('answers a question with its reactions', async ({ page }) => {
    await page.goto('/ask');
    await expect(page.getByText(/in development/)).toBeVisible();
    await page.getByRole('textbox', { name: 'Question' }).fill('reactions that use acetyl chloride');
    await page.getByRole('button', { name: 'Ask' }).click();
    await expect(page.getByText('Three reactions use acetyl chloride.')).toBeVisible();
    await expect(page.getByRole('link', { name: REACTION_LINK })).toHaveText([
      'ord-viewer0102',
      'ord-viewer0103',
      'ord-viewer0201',
    ]);
    await page.getByRole('button', { name: 'The query it ran' }).click();
    await expect(page.getByText('"same_compound"', { exact: false })).toBeVisible();
  });

  test('answers a question with a table', async ({ page }) => {
    await page.goto(`/ask?${new URLSearchParams({ q: 'how many reactions are in each dataset' })}`);
    const table = page.getByRole('table');
    await expect(table).toContainText('ord_dataset-viewer01');
    await expect(table).toContainText('3');
  });

  test('says why it cannot answer a question', async ({ page }) => {
    await page.goto(`/ask?${new URLSearchParams({ q: 'what does pyridine cost' })}`);
    await expect(page.getByRole('alert')).toContainText('no script');
  });
  ```

  Run it locally as F4.8's Step 5 does. Expected: every spec passes.

- [ ] **Step 2: Floors and docs.** Raise the coverage floors to the measured values. In
  `CLAUDE.md`, say that `ord_viewer.testing:e2e_app` answers `/api/ask` from
  `ASK_SCRIPTS`, and that the viewer's `/ask` is unlisted.
- [ ] **Step 3: Open the PR.** Title "Ask about reactions in the viewer". Run the checks,
  open it, bind it, turn on auto-fix, and run `review-pr`.

## After F6

- Record, in a Refinements list like this plan's, where F4–F6 departed from these tasks,
  and update the design to match.
- Mark step 4 done in the entry's README, and leave step 5 its inheritance: the image,
  its contract, and the corpus it needs.
