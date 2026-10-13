# The viewer: implementation plan for F1–F3

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; F4–F6 get their own plan once F3 merges, against the scaffold and
  harness F2 and F3 ship
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the editor's Ketcher dialog into the shared package (F1), scaffold
`frontend/apps/viewer` with its typed API layer (F2), and build the viewer's image with
a smoke test, one image job per app, and the root's single-app files moved to the app or
language they serve (F3).

**Architecture:** F1 splits the dialog into a light `StructureDialog`, which apps import
from `@open-reaction-database/ui/ketcher`, and a heavy `KetcherDialog` it loads with
`React.lazy` the first time it opens. F2 adds a Vite app on the shared package whose API
types are generated from `backend/viewer/openapi.json`, a file a pytest pins to the
backend's routes. F3 adds `deploy/viewer`, an nginx and uvicorn image for `linux/arm64`
that stops when either process exits, and an `Images` workflow that builds each app's
image with a layer cache and checks the viewer's through nginx.

**Tech Stack:** npm workspaces, React 19, Vite 6, Mantine 7, wouter 3.9, TanStack Query
5, openapi-typescript 7, Vitest 4 with happy-dom, Playwright, Ketcher 3.15, Python 3.12
with uv, FastAPI, Docker Buildx with the GitHub Actions cache, nginx, and supervisord.

**Spec:** [`viewer-frontend-design.md`](viewer-frontend-design.md), beside this file.
Read it first. Where this plan refines the design, the
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
  alone. Once the PR merges, remove the worktree with
  `git -C ~/ord/ord-app worktree remove ~/ord/worktrees/ord-app/<branch>`. Never commit
  to `main`; never force-push.
- Order: F1, F2, F3. F1 is independent of F2 and F3 and may land after them, but before
  F5.
- The repository holds two independent apps that share code. Each app gets its own CI
  jobs; only checks whose configuration spans the repository stay shared. Existing job
  names stay as they are (`test_python`, `test_python_viewer`, `test_ui`, `test_e2e`,
  `check_python`, `check_duplication`, `check_license_headers`, `lint_and_build_ui`),
  since branch protection matches checks by name. Every required job runs on every PR,
  with no path filters.
- The editor behaves as it does today through all three PRs. Its existing test
  assertions stay; only what a moved component is imported from changes.
- Frontend: the shared package is imported only through its `exports`. Inside the
  package and the viewer, files import each other through `#…` subpath imports or from
  the same folder, never `../`. Type-check with `npm run typecheck` (`tsc -b`), never a
  bare `tsc --noEmit`.
- Pins: the viewer's dependencies use the same ranges as the editor's where both depend
  on a package. GitHub Actions are pinned to commit SHAs with a `# vX.Y.Z` comment, and
  Docker images to `tag@sha256:<index digest>`, copied from `deploy/editor/Dockerfile`.
- Every new `.py`, `.ts`, `.tsx`, `.mjs`, `.scss`, `.html`, `.toml`, `.yaml`, `.conf`,
  and `.sh` file starts with the Apache-2.0 header, copyright 2026, "Open Reaction
  Database Project Authors". The addlicense pre-commit hook adds it; the code blocks
  below omit it. A moved file keeps its header. JSON files carry none.
- Python style: no lazy imports; free functions rather than `@staticmethod`;
  Google-style docstrings whose first line fits on one line; no abbreviated words in
  identifiers; every `pytest.raises` has a `match=`. TypeScript style follows the
  surrounding files: `Readonly<…>` props, `Array<T>` rather than `T[]`, type-only
  imports marked `type`.
- American spelling. Comments describe the code as it is, never the change that made
  it.
- Shell commands are for zsh: quote globs meant for a program, and pass lists as arrays.
- Commit messages end with the `Co-Authored-By:` trailer naming the model you run as. PR
  bodies use `## Summary`, `## Changes`, `## Testing`, `## Notes` (delete an empty
  section), one line per paragraph, and end with the Claude Code footer. Run the
  `review-pr` skill on each PR once its first push is up.
- Files under `.claude/skills/` are write-protected in the sandbox; ask the user before
  editing one.

## Review Focus

Inputs the design implies but states no behavior for, most likely to bite first. Each
has a test in the task named.

1. **A backend that cannot open its corpus:** the container stops, so the task fails
   where it can be seen, rather than serving the SPA with a 502 behind every `/api/`
   request (F3.3, the empty-corpus step).
2. **A 422 whose body is a list of validation errors** rather than a message: the user
   reads the errors' messages, not `[object Object]` (F2.3, `client.test.ts`).
3. **ord-interface's shared links:** `/selected-set?reaction_id=a&reaction_id=b` lands
   on `/reactions?id=a&id=b` with both IDs in order, and an ID holding a character a path
   must escape survives `/id/:id` (F2.2, `routes.test.tsx`).
4. **Reopening the structure dialog** after a save or a cancel: the canvas shows the new
   `initial` structure, not the last drawing or a blank one, and Ketcher's chunk loads
   once (F1.1).
5. **Asks faster than the limit:** past the burst, nginx answers 429 without reaching
   the backend, and a body past 128 KiB answers 413 (F3.2, `smoke_test.sh`).

## Refinements to the design

- **The package loads Ketcher lazily, not each app.** Apps import `StructureDialog`
  statically from `./ketcher`; it renders nothing until first opened, then loads
  `KetcherDialog` through `React.lazy` and keeps it mounted. One wrapper serves both
  apps, and only `KetcherDialog.tsx` may import Ketcher's packages.
- **Ketcher's polyfills move into the loader.** Ketcher's modules read Node's `global`
  and `Buffer`. The loader installs them before it imports `KetcherDialog`, so a host
  provides only Vite's `define: {'process.env': {}}`, and the editor's `main.tsx` drops
  its copy. A bare side-effect import would not do: the package's `sideEffects` lists
  only stylesheets, so a production build may drop it.
- **The generated `schema.ts` keeps its license header.** addlicense writes the header
  once, when the file is first committed; the generator keeps whatever header the
  committed file starts with, so regenerating in a later year changes nothing. ESLint and
  jscpd skip the file, and coverage excludes it.
- **The image stops when either process stops.** supervisord runs uvicorn and nginx
  with no restarts, and an event listener stops supervisord when either exits.
- **`ruff.toml` moves to `backend/`**, beside the Python projects, as `frontend/` holds
  the JavaScript configuration. Its `src` becomes `["editor", "viewer"]`, which ruff
  resolves against the file's own directory.
- **The viewer's page carries ord-interface's Google Analytics tag** (`G-REEDLYB0ZJ`),
  as the apex domain's pages do today.
- **Ports.** The viewer's dev server listens on 5174 and `vite preview` on 4174, beside
  the editor's 5173; both send `/api` to the backend on 8001, or to `ORD_VIEWER_API`.

These came from executing F1–F3 (ord-app#890, #891, and #893); the design file has been
updated to match.

- **The editor keeps its polyfill.** Removing it blanked the editor, since csv-parse
  reads `Buffer` as it loads; the E2E caught it. The editor keeps `buffer` and the
  polyfill in `main.tsx`, and the loader's `??=` install is a no-op there.
- **Each opening gets its own Ketcher.** The modal unmounts the canvas on close, so
  `KetcherDialog` forgets the instance then, and the plan's "clears the canvas when
  closed" test became "loads a new initial structure while open". A chunk that fails to
  load stays inside the dialog (`LoadBoundary`, with Close and Try again, retrying
  with a fresh `React.lazy`). The E2E reads the saved structure back.
- **Path parameters.** wouter matches routes against `decodeURI(path)`, which leaves
  reserved escapes such as `%2F`, so the plan's `encodeURIComponent` encoded them
  twice. `src/routeParams.ts`'s `routeParam` decodes the rest, and F4–F6's pages read
  `:datasetId` and `:reactionId` through it.
- **The client's errors.** `ApiError` records whether the backend wrote the response:
  nginx's own 502 or 504, during the backend's startup or past its timeout, shows the
  503's message rather than the ask's or the search's. A list of validation errors with
  no messages falls back to the status text, where the plan's code returned `''`.
- **Request types keep defaulted fields optional** (`defaultNonNullable: false`), so a
  `Query` may leave out an order's `descending` or a structure's `chirality`;
  `types.test.ts` type-checks three such requests.
- **Narrow screens.** The navigation is a row from `sm` up and a menu below it; About's
  sections stack below `sm` (`Grid`, where `SimpleGrid` with a three-column span added
  empty columns).
- **SonarCloud skips `schema.ts`** through a new `.sonarcloud.properties`, after its 805
  repeated lines failed the duplication gate. Its `S8707` on `testing.main()`, a
  command-line path the caller chooses, is a false positive marked in SonarCloud.
- **The image's exit code.** supervisord exits 0 however it stops, so `start.sh`, the
  container's command, exits 0 only for a requested stop that supervisord carried out
  cleanly, keeps supervisord's own nonzero code, and is 1 otherwise; it clears the
  marker `exit_on_failure.sh` leaves, which a restarted container would keep.
  `build_viewer_image` checks both codes.
- **The smoke test.** It reads each response whole before matching, since `curl | grep
  -q` can cut curl off and fail under `pipefail`; every request has a time limit (5 s to
  connect, 30 s in all), the wait for the backend a three-minute deadline, and each image
  job a 30-minute limit.
- **`/api/ask`'s model calls make one attempt each** (ord-app#894): the SDK's two default
  retries put an ask's worst case near 230 s, past nginx's 150 s.
- **F3.4's compose check** compared `docker compose config` before and after the move,
  rather than running `up` and `down`, which would have removed a running `ord-app`
  stack.
- **F2 outgrew the plan's test counts**: 51 viewer tests where the plan wrote 35.

---

## PR F1: the structure dialog moves into the shared package

Branch `shared-structure-dialog`, in its own worktree from `origin/main`.

### Task F1.1: `StructureDialog` and `KetcherDialog` in `packages/ui`

**Files:**

- Create: `frontend/packages/ui/src/ketcher/structure.types.ts`,
  `KetcherDialog.tsx`, `KetcherDialog.test.tsx`, `StructureDialog.tsx`,
  `StructureDialog.test.tsx`, `index.ts`
- Move: `frontend/apps/editor/src/features/reactions/ComponentsKetcherEditor/componentsKetcherEditor.module.scss`
  → `frontend/packages/ui/src/ketcher/structureDialog.module.scss`
- Modify: `frontend/packages/ui/package.json`, `frontend/packages/ui/README.md`,
  `frontend/eslint.config.mjs`, `frontend/package-lock.json`, `CLAUDE.md`

**Interfaces:**

- Produces: `@open-reaction-database/ui/ketcher` exporting `StructureDialog`,
  `type StructureDialogProps`, and `type StructureFormat`:

  ```ts
  type StructureFormat = 'molfile' | 'smiles' | 'smarts';
  interface StructureDialogProps extends PropsWithChildren {
    opened: boolean;
    onClose: () => void;
    initial: string;
    format: StructureFormat;
    onSave: (structure: string) => void;
  }
  ```

- [ ] **Step 1: Worktree and baseline.** Create the worktree for `shared-structure-dialog`
  as the Global Constraints show, then from `frontend/`:

  ```bash
  npm test -w packages/ui -- --run 2>&1 | tail -3
  (cd apps/editor && npx vitest run 2>&1 | tail -3)
  ```

  Record both totals; the editor's must be unchanged at the end of F1.2, less the three
  `ComponentsKetcherEditor` tests that move and plus the ones F1.2 adds.

- [ ] **Step 2: Declare the subpath and the dependencies.** In
  `frontend/packages/ui/package.json`, add the export after `./shell`:

  ```json
  "./ketcher": "./src/ketcher/index.ts",
  ```

  and to `dependencies`, keeping alphabetical order:

  ```json
  "buffer": "^6.0.3",
  "ketcher-core": "^3.15.0",
  "ketcher-react": "^3.15.0",
  "ketcher-standalone": "^3.15.0",
  ```

  Then from `frontend/`: `npm install --ignore-scripts`. The lockfile should gain only the
  package's new edges; `git diff --stat package-lock.json` naming any version change is a
  bug in this step.

- [ ] **Step 3: Move the stylesheet.**

  ```bash
  git mv frontend/apps/editor/src/features/reactions/ComponentsKetcherEditor/componentsKetcherEditor.module.scss \
    frontend/packages/ui/src/ketcher/structureDialog.module.scss
  ```

- [ ] **Step 4: Write the types.** `frontend/packages/ui/src/ketcher/structure.types.ts`:

  ```ts
  import type { PropsWithChildren } from 'react';

  /** What a drawing is saved as: a molfile, SMILES, or SMARTS. */
  export type StructureFormat = 'molfile' | 'smiles' | 'smarts';

  export interface StructureDialogProps extends PropsWithChildren {
    opened: boolean;
    onClose: () => void;
    /** The structure the canvas opens with, in any notation Ketcher reads; '' for none. */
    initial: string;
    /** The notation onSave receives the drawing in. */
    format: StructureFormat;
    /** Receives the drawing when Save is clicked, after which the dialog closes. */
    onSave: (structure: string) => void;
  }
  ```

  `children` are fields shown beside the buttons, such as the editor's Details.

- [ ] **Step 5: Write the failing tests for `KetcherDialog`.**
  `frontend/packages/ui/src/ketcher/KetcherDialog.test.tsx`, adapted from the editor's
  `ComponentsKetcherEditor.test.tsx`:

  ```tsx
  import { describe, expect, it, vi } from 'vitest';
  import { waitFor } from '@testing-library/react';
  import userEvent from '@testing-library/user-event';
  import type * as ReactNS from 'react';
  import { renderWithMantine } from '#testing/renderWithMantine.tsx';
  import { KetcherDialog } from './KetcherDialog.tsx';
  import type { StructureDialogProps } from './structure.types.ts';

  // Ketcher's editor needs a WASM struct service and a canvas, which happy-dom lacks. The
  // stubs keep the API the dialog relies on (onInit, setMolecule, and the getters), which a
  // Ketcher upgrade could break.
  const ketcher = {
    setMolecule: vi.fn((_structure: string) => Promise.resolve()),
    getMolfile: vi.fn(() => Promise.resolve('MOLFILE')),
    getSmiles: vi.fn(() => Promise.resolve('SMILES')),
    getSmarts: vi.fn(() => Promise.resolve('SMARTS')),
  };

  vi.mock('ketcher-standalone', () => ({
    StandaloneStructServiceProvider: class {},
  }));

  vi.mock('ketcher-react', async () => {
    const React = (await vi.importActual('react')) as typeof ReactNS;
    return {
      // Calls the host's onInit once on mount, as Ketcher does when it is ready.
      Editor: (props: Readonly<{ onInit?: (instance: typeof ketcher) => void }>) => {
        React.useEffect(() => {
          props.onInit?.(ketcher);
        }, [props]);
        return React.createElement('div', { 'data-testid': 'ketcher-editor' });
      },
    };
  });

  vi.mock('ketcher-react/dist/index.css', () => ({}));

  function props(overrides: Partial<StructureDialogProps> = {}): StructureDialogProps {
    return {
      opened: true,
      onClose: vi.fn(),
      onSave: vi.fn(),
      initial: 'CCO',
      format: 'molfile',
      ...overrides,
    };
  }

  describe('KetcherDialog', () => {
    it('loads the initial structure once Ketcher initializes', async () => {
      renderWithMantine(<KetcherDialog {...props()} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenCalledWith('CCO'));
    });

    it('loads the initial structure again when reopened', async () => {
      const { rerender } = renderWithMantine(<KetcherDialog {...props()} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenCalledWith('CCO'));
      rerender(<KetcherDialog {...props({ opened: false })} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenLastCalledWith(''));
      rerender(<KetcherDialog {...props({ initial: 'CCN' })} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenLastCalledWith('CCN'));
    });

    it('clears the canvas when closed', async () => {
      const { rerender } = renderWithMantine(<KetcherDialog {...props()} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenCalledWith('CCO'));
      rerender(<KetcherDialog {...props({ opened: false })} />);
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenLastCalledWith(''));
    });

    it.each([
      ['molfile', 'MOLFILE', ketcher.getMolfile],
      ['smiles', 'SMILES', ketcher.getSmiles],
      ['smarts', 'SMARTS', ketcher.getSmarts],
    ] as const)('saves the drawing as %s and closes', async (format, saved, getter) => {
      const onSave = vi.fn();
      const onClose = vi.fn();
      const { getByRole } = renderWithMantine(
        <KetcherDialog {...props({ format, onSave, onClose })} />,
      );
      await waitFor(() => expect(ketcher.setMolecule).toHaveBeenCalled());
      await userEvent.click(getByRole('button', { name: 'Save' }));
      await waitFor(() => {
        expect(getter).toHaveBeenCalled();
        expect(onSave).toHaveBeenCalledWith(saved);
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('shows the host’s fields beside the buttons', () => {
      const { getByText } = renderWithMantine(
        <KetcherDialog {...props()}>
          <span>Details field</span>
        </KetcherDialog>,
      );
      expect(getByText('Details field')).toBeInTheDocument();
    });
  });
  ```

  The vitest config's `mockReset: true` resets the stub's calls before each test and
  restores each `vi.fn(impl)` to its implementation.

- [ ] **Step 6: Run them to see them fail.**

  ```bash
  npm test -w packages/ui -- --run src/ketcher/KetcherDialog.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import "./KetcherDialog.tsx"`.

- [ ] **Step 7: Write `KetcherDialog`.**
  `frontend/packages/ui/src/ketcher/KetcherDialog.tsx`, from the editor's
  `ComponentsKetcherEditor.tsx`:

  ```tsx
  import { Button, Flex, Grid, Modal } from '@mantine/core';
  import { Editor } from 'ketcher-react';
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore
  import { StandaloneStructServiceProvider } from 'ketcher-standalone';
  import 'ketcher-react/dist/index.css';
  import type { Ketcher } from 'ketcher-core';
  import { useEffect, useState } from 'react';
  import classes from './structureDialog.module.scss';
  import type { StructureDialogProps, StructureFormat } from './structure.types.ts';

  const appWindow = globalThis as unknown as { ketcher: Ketcher | null };
  const structServiceProvider = new StandaloneStructServiceProvider();

  const READERS: Record<StructureFormat, (ketcher: Ketcher) => Promise<string>> = {
    molfile: ketcher => ketcher.getMolfile(),
    smiles: ketcher => ketcher.getSmiles(),
    smarts: ketcher => ketcher.getSmarts(),
  };

  /** Ketcher's canvas in a modal; StructureDialog loads it the first time it opens. */
  export function KetcherDialog({
    opened,
    onClose,
    initial,
    format,
    onSave,
    children,
  }: Readonly<StructureDialogProps>) {
    const [ketcher, setKetcher] = useState<Ketcher | null>(null);

    // The canvas is cleared on close, so each opening loads the initial structure again.
    useEffect(() => {
      if (ketcher && opened) {
        void ketcher.setMolecule(initial);
      }
    }, [ketcher, opened, initial]);

    useEffect(() => {
      if (ketcher && !opened) {
        void ketcher.setMolecule('');
      }
    }, [ketcher, opened]);

    const handleSave = () => {
      if (ketcher) {
        void READERS[format](ketcher).then(structure => {
          onSave(structure);
          onClose();
        });
      }
    };

    return (
      <Modal
        opened={opened}
        onClose={onClose}
        classNames={{ content: classes.wrapper, body: classes.body }}
        withCloseButton={false}
      >
        <div className={classes.editorWrapper}>
          <Editor
            structServiceProvider={structServiceProvider}
            staticResourcesUrl={import.meta.env.BASE_URL as string}
            onInit={instance => {
              setKetcher(instance);
              // Ketcher's own modules read the instance from this global.
              appWindow.ketcher = instance;
            }}
            errorHandler={console.error}
          />
        </div>
        <Grid
          className={classes.actions}
          align="flex-end"
        >
          <Grid.Col span={6}>{children}</Grid.Col>
          <Grid.Col span={6}>
            <Flex
              gap="sm"
              justify="flex-end"
            >
              <Button
                variant="default"
                onClick={onClose}
              >
                Cancel
              </Button>
              <Button onClick={handleSave}>Save</Button>
            </Flex>
          </Grid.Col>
        </Grid>
      </Modal>
    );
  }
  ```

- [ ] **Step 8: Run the `KetcherDialog` tests to see them pass.** Same command as Step 6.
  Expected: 7 passed.

- [ ] **Step 9: Write the failing tests for `StructureDialog`.**
  `frontend/packages/ui/src/ketcher/StructureDialog.test.tsx`:

  ```tsx
  import { describe, expect, it, vi } from 'vitest';
  import type * as ReactNS from 'react';
  import { renderWithMantine } from '#testing/renderWithMantine.tsx';
  import { StructureDialog } from './StructureDialog.tsx';
  import type { StructureDialogProps } from './structure.types.ts';

  // Counts how often the dialog's module is evaluated, which happens when it is imported.
  const evaluations = vi.hoisted(() => ({ count: 0 }));

  vi.mock('./KetcherDialog.tsx', async () => {
    evaluations.count += 1;
    const React = (await vi.importActual('react')) as typeof ReactNS;
    return {
      KetcherDialog: (props: Readonly<StructureDialogProps>) =>
        React.createElement(
          'div',
          { 'data-testid': 'ketcher-dialog', 'data-opened': String(props.opened) },
          props.initial,
        ),
    };
  });

  function props(opened: boolean, initial = 'CCO'): StructureDialogProps {
    return { opened, initial, onClose: vi.fn(), onSave: vi.fn(), format: 'smiles' };
  }

  describe('StructureDialog', () => {
    it('loads Ketcher only when first opened, and keeps it mounted after closing', async () => {
      const { queryByTestId, findByTestId, getByTestId, rerender } = renderWithMantine(
        <StructureDialog {...props(false)} />,
      );
      expect(queryByTestId('ketcher-dialog')).not.toBeInTheDocument();
      expect(evaluations.count).toBe(0);

      rerender(<StructureDialog {...props(true)} />);
      expect(await findByTestId('ketcher-dialog')).toHaveAttribute('data-opened', 'true');
      expect(evaluations.count).toBe(1);

      rerender(<StructureDialog {...props(false)} />);
      expect(getByTestId('ketcher-dialog')).toHaveAttribute('data-opened', 'false');

      rerender(<StructureDialog {...props(true, 'CCN')} />);
      expect(getByTestId('ketcher-dialog')).toHaveTextContent('CCN');
      expect(evaluations.count).toBe(1);
    });
  });
  ```

  The steps share one test because the module is evaluated once per file, so the count
  is meaningful only in order.

- [ ] **Step 10: Run it to see it fail.**

  ```bash
  npm test -w packages/ui -- --run src/ketcher/StructureDialog.test.tsx
  ```

  Expected: FAIL, `Failed to resolve import "./StructureDialog.tsx"`.

- [ ] **Step 11: Write `StructureDialog` and the entry file.**
  `frontend/packages/ui/src/ketcher/StructureDialog.tsx`:

  ```tsx
  import { Center, Loader, Modal } from '@mantine/core';
  import { lazy, Suspense, useState } from 'react';
  import type { StructureDialogProps } from './structure.types.ts';

  /**
   * Imports the dialog, after installing the Node globals Ketcher's modules read.
   *
   * They are installed here, before the import, rather than by a module imported for its
   * side effects: the package's `sideEffects` lists only stylesheets, so a production build
   * may drop such an import.
   */
  async function loadKetcherDialog() {
    const { Buffer } = await import('buffer');
    globalThis.global ??= globalThis;
    globalThis.Buffer ??= Buffer;
    const { KetcherDialog } = await import('./KetcherDialog.tsx');
    return { default: KetcherDialog };
  }

  const KetcherDialog = lazy(loadKetcherDialog);

  /**
   * Draws a structure in Ketcher, saving it as `format`.
   *
   * Ketcher loads the first time the dialog opens, in a chunk of its own, and stays mounted
   * after the dialog closes, so later openings are immediate.
   */
  export function StructureDialog(props: Readonly<StructureDialogProps>) {
    const [hasOpened, setHasOpened] = useState(props.opened);
    if (props.opened && !hasOpened) {
      setHasOpened(true);
    }
    if (!hasOpened) {
      return null;
    }
    return (
      <Suspense
        fallback={
          <Modal
            opened={props.opened}
            onClose={props.onClose}
            withCloseButton={false}
          >
            <Center p="xl">
              <Loader />
            </Center>
          </Modal>
        }
      >
        <KetcherDialog {...props} />
      </Suspense>
    );
  }
  ```

  `frontend/packages/ui/src/ketcher/index.ts`:

  ```ts
  export { StructureDialog } from './StructureDialog.tsx';
  export type { StructureDialogProps, StructureFormat } from './structure.types.ts';
  ```

- [ ] **Step 12: Run the package's tests.**

  ```bash
  npm test -w packages/ui -- --run
  ```

  Expected: every test passes, the Step 1 total plus 8.

- [ ] **Step 13: Confine Ketcher in ESLint.** In `frontend/eslint.config.mjs`:

  1. Add `ketcher` to the barrel pattern in `PACKAGE_IMPORT_PATTERNS`:

     ```js
     regex: String.raw`^#(reaction(/[^/]+)?|testing|theme|display|shell|ketcher)/index\.ts$`,
     ```

  2. Below `APP_STATE_IMPORTS`, add:

     ```js
     // Ketcher, which only the structure dialog's lazily loaded module may import: any
     // other import would put Ketcher in an app's first download.
     const KETCHER_PATTERN = {
       group: ['ketcher-*'],
       message: 'Only src/ketcher/KetcherDialog.tsx imports Ketcher, which StructureDialog loads lazily.',
     };
     ```

  3. Append `KETCHER_PATTERN` to the `patterns` of the `packages/ui/**` block and of the
     `packages/ui/src/shell/**` block.
  4. After the shell block, add a block for the one module allowed to import it:

     ```js
     {
       files: ['packages/ui/src/ketcher/KetcherDialog.tsx'],
       rules: {
         'no-restricted-imports': [
           'error',
           {
             patterns: [
               ...PACKAGE_IMPORT_PATTERNS,
               {
                 group: [...APP_STATE_IMPORTS, 'wouter'],
                 message:
                   'The shared package stays free of app state, transport, and routing.',
               },
             ],
           },
         ],
       },
     },
     ```

  Check that the rule bites: add `import 'ketcher-core';` to `StructureDialog.tsx`, run
  `npx eslint packages/ui/src/ketcher` from `frontend/`, and expect the "Only
  src/ketcher/KetcherDialog.tsx imports Ketcher" error; then remove the line and expect
  no errors.

- [ ] **Step 14: Document the subpath.** In `frontend/packages/ui/README.md`, add
  `…/ketcher` to the opening paragraph's list of subpaths, after `…/shell`, and append
  to "What a host provides":

  ```markdown
  - For `@open-reaction-database/ui/ketcher`: `define: { 'process.env': {} }` in its Vite
    config, since Ketcher reads `process.env`. `StructureDialog` installs the `global` and
    `Buffer` Ketcher's modules expect, and loads Ketcher the first time it opens.
  ```

  In `CLAUDE.md`'s `packages/ui/` bullet, add "the Ketcher structure dialog
  (`src/ketcher/`: `StructureDialog`, which loads `KetcherDialog` lazily)" after the
  page shell, add `…/ketcher` to the exports list, and extend the lint sentence's last
  clause to "and wouter outside `src/shell/` and Ketcher outside
  `src/ketcher/KetcherDialog.tsx`."

- [ ] **Step 15: Lint, type-check, and commit.** From `frontend/`:

  ```bash
  npm run lint:check && npm run typecheck && npm test -w packages/ui -- --run 2>&1 | tail -3
  ```

  Then from the worktree's root:

  ```bash
  git add frontend/packages/ui frontend/eslint.config.mjs frontend/package-lock.json CLAUDE.md
  git status --short   # only the files above, and the moved stylesheet
  git commit -m "Move the Ketcher dialog into the shared package as StructureDialog"
  ```

### Task F1.2: The editor uses `StructureDialog`, with an E2E check

**Files:**

- Modify: `frontend/apps/editor/src/features/reactions/ComponentsKetcherEditor/ComponentsKetcherEditor.tsx`,
  `ComponentsKetcherEditor.test.tsx`, `frontend/apps/editor/src/main.tsx`,
  `frontend/apps/editor/package.json`, `frontend/package-lock.json`
- Create: `frontend/apps/editor/e2e/structureDialog.spec.ts`

**Interfaces:**

- Consumes: `StructureDialog` from `@open-reaction-database/ui/ketcher` (F1.1);
  `MoleculeEditorProps` from `@open-reaction-database/ui/reaction`.
- Produces: `ComponentsKetcherEditor({opened, onClose, identifier, onSave})`, unchanged
  in signature, which the editor's slot tables already use.

- [ ] **Step 1: Write the failing tests.** Replace
  `ComponentsKetcherEditor.test.tsx`'s body below the license header with:

  ```tsx
  import { describe, expect, it, vi } from 'vitest';
  import { waitFor } from '@testing-library/react';
  import userEvent from '@testing-library/user-event';
  import type * as ReactNS from 'react';
  import type { StructureDialogProps } from '@open-reaction-database/ui/ketcher';
  import { renderWithMantine } from 'test/renderWithMantine.tsx';
  import { ComponentsKetcherEditor } from './ComponentsKetcherEditor.tsx';

  // The dialog itself is tested in the shared package; this stub shows what the editor
  // passes it and saves a fixed molfile.
  vi.mock('@open-reaction-database/ui/ketcher', async () => {
    const React = (await vi.importActual('react')) as typeof ReactNS;
    return {
      StructureDialog: (props: Readonly<StructureDialogProps>) =>
        props.opened
          ? React.createElement(
              'div',
              {
                'data-testid': 'structure-dialog',
                'data-initial': props.initial,
                'data-format': props.format,
              },
              props.children,
              React.createElement(
                'button',
                { type: 'button', onClick: () => props.onSave('MOLFILE') },
                'Save',
              ),
            )
          : null,
    };
  });

  const identifier = { value: 'CCO', details: 'ethanol' };

  describe('ComponentsKetcherEditor', () => {
    it('opens the identifier’s structure and asks for a molfile', () => {
      const { getByTestId } = renderWithMantine(
        <ComponentsKetcherEditor
          opened
          onClose={vi.fn()}
          onSave={vi.fn()}
          identifier={identifier}
        />,
      );
      const dialog = getByTestId('structure-dialog');
      expect(dialog).toHaveAttribute('data-initial', 'CCO');
      expect(dialog).toHaveAttribute('data-format', 'molfile');
    });

    it('saves the drawing with the Details field’s value', async () => {
      const onSave = vi.fn();
      const { getByLabelText, getByRole } = renderWithMantine(
        <ComponentsKetcherEditor
          opened
          onClose={vi.fn()}
          onSave={onSave}
          identifier={identifier}
        />,
      );
      const details = getByLabelText('Details');
      await userEvent.clear(details);
      await userEvent.type(details, 'drawn again');
      await userEvent.click(getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(onSave).toHaveBeenCalledWith({ value: 'MOLFILE', details: 'drawn again' }),
      );
    });

    it('starts a new drawing blank, with the default details', () => {
      const { getByTestId, getByLabelText } = renderWithMantine(
        <ComponentsKetcherEditor
          opened
          onClose={vi.fn()}
          onSave={vi.fn()}
          identifier={null}
        />,
      );
      expect(getByTestId('structure-dialog')).toHaveAttribute('data-initial', '');
      expect(getByLabelText('Details')).toHaveValue('Drawn with Ketcher');
    });
  });
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd frontend/apps/editor && npx vitest run src/features/reactions/ComponentsKetcherEditor
  ```

  Expected: FAIL; the real component renders Ketcher's `Editor`, not the stub's
  `structure-dialog`.

- [ ] **Step 3: Rewrite the component as a wrapper.** Replace
  `ComponentsKetcherEditor.tsx`'s body below the license header with:

  ```tsx
  import { TextInput } from '@mantine/core';
  import { useField } from '@mantine/form';
  import { useEffect } from 'react';
  import { StructureDialog } from '@open-reaction-database/ui/ketcher';
  import type { MoleculeEditorProps } from '@open-reaction-database/ui/reaction';

  /** The editor's molecule editor: Ketcher, saving a molfile with the drawing's details. */
  export function ComponentsKetcherEditor({
    opened,
    onClose,
    identifier,
    onSave,
  }: Readonly<MoleculeEditorProps>) {
    const initialDetails = identifier?.details || 'Drawn with Ketcher';
    const { getInputProps, getValue, setValue } = useField({
      mode: 'controlled',
      initialValue: initialDetails,
    });

    useEffect(() => {
      setValue(initialDetails);
    }, [setValue, initialDetails]);

    return (
      <StructureDialog
        opened={opened}
        onClose={onClose}
        initial={identifier?.value ?? ''}
        format="molfile"
        onSave={value => onSave({ value, details: getValue() })}
      >
        <TextInput
          placeholder="Details"
          label="Details"
          {...getInputProps()}
        />
      </StructureDialog>
    );
  }
  ```

- [ ] **Step 4: Run them to see them pass.** Same command as Step 2. Expected: 3 passed.

- [ ] **Step 5: Drop the editor's own Ketcher wiring.** In
  `frontend/apps/editor/src/main.tsx`, delete the `buffer` import, the comment about
  draft-js, and the two lines that set `globalThis.global` and `globalThis.Buffer`;
  `StructureDialog` installs them now. Confirm nothing else in the editor imports
  Ketcher's packages or `buffer`:

  ```bash
  grep -rnE "from '(ketcher-[a-z]+|buffer)'" frontend/apps/editor/src
  ```

  Expected: no output. Then remove `buffer`, `ketcher-react`, and `ketcher-standalone`
  from `frontend/apps/editor/package.json`'s `dependencies` and run
  `npm install --ignore-scripts` from `frontend/`. Keep `define: {'process.env': {}}` in
  the editor's `vite.config.ts`, which the package's README now names as a host's.

- [ ] **Step 6: Write the E2E check.** `frontend/apps/editor/e2e/structureDialog.spec.ts`:

  ```ts
  import { expect, test } from '@playwright/test';
  import { seedReaction } from './seed.ts';

  // Ketcher sets this global once its canvas is ready.
  interface KetcherWindow {
    ketcher?: { setMolecule(structure: string): Promise<void> } | null;
  }

  test('draws a molblock identifier in Ketcher and saves it', async ({ page, request }) => {
    // Its own reaction, since saving changes it.
    const { datasetId, reactionId } = await seedReaction(request);
    await page.goto(`/datasets/${datasetId}/reactions/${reactionId}`, {
      waitUntil: 'domcontentloaded',
    });
    await expect(page.getByText('acid', { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
    await page.getByText('Add Molblock Identifier').click();
    await page.waitForFunction(
      () => Boolean((globalThis as KetcherWindow).ketcher),
      undefined,
      { timeout: 60_000 },
    );
    await page.evaluate(() => (globalThis as KetcherWindow).ketcher?.setMolecule('CCO'));
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    await expect(page.getByText('Drawn with Ketcher')).toBeVisible();
  });
  ```

  If the first Edit opens the input's drawer and its component's form sits one drawer
  deeper, add the click that opens it (the drawer's first `Edit`) before "Add Molblock
  Identifier", as `reactionPage.spec.ts`'s drawer test shows the first level.

- [ ] **Step 7: Run the editor's suites.** Start the no-auth stack as `CLAUDE.md`
  describes (`scripts/dev-e2e.sh`, with Postgres from `docker compose up -d db`), then
  from `frontend/`:

  ```bash
  (cd apps/editor && npx vitest run 2>&1 | tail -3)
  npm run test:e2e -w apps/editor -- structureDialog.spec.ts reactionPage.spec.ts
  ```

  Expected: the unit total from Step 1 of F1.1 (less 3, plus 3), and both specs
  passing. In the browser's network panel or the dev server's log, Ketcher's modules
  load only after "Add Molblock Identifier" is clicked.

- [ ] **Step 8: Check, then commit.**

  ```bash
  (cd frontend && npm run lint:check && npm run typecheck && npm run build -w apps/editor)
  git add frontend/apps/editor frontend/package-lock.json
  git commit -m "Draw the editor's molblocks through the shared StructureDialog"
  ```

  `npm run build -w apps/editor` needs the Auth0 variables only when
  `ORD_APP_REQUIRE_AUTH0` is set, so it runs as is. In its output, Ketcher's modules sit
  in a chunk of their own, apart from `index-*.js`.

### Task F1.3: Open the PR

- [ ] **Step 1:** Push, and open the PR titled "Move the Ketcher dialog into the shared
  package". Its body names `StructureDialog`'s lazy load, the polyfills' move, and the
  new E2E check, and its Notes say F5's search form is the dialog's second host.
- [ ] **Step 2:** Run `review-pr` on it.

---

## PR F2: the viewer's scaffold

Branch `viewer-scaffold`, in its own worktree from `origin/main`.

### Task F2.1: The committed OpenAPI document

**Files:**

- Create: `backend/viewer/ord_viewer/openapi.py`, `openapi_test.py`,
  `backend/viewer/openapi.json`
- Modify: `CLAUDE.md`

**Interfaces:**

- Produces: `backend/viewer/openapi.json`, the document F2.3 generates types from;
  `python -m ord_viewer.openapi`, run from `backend/viewer`, which rewrites it.

- [ ] **Step 1: Write the failing tests.** `backend/viewer/ord_viewer/openapi_test.py`:

  ```python
  """The committed OpenAPI document, which the viewer's frontend types are built from."""

  import json

  from ord_viewer import openapi
  from ord_viewer.main import app


  def test_the_committed_document_matches_the_app():
      assert openapi.DOCUMENT_PATH.read_text() == openapi.render(), (
          "backend/viewer/openapi.json is stale: run `uv run python -m ord_viewer.openapi`"
          " from backend/viewer, then `npm run generate:api -w apps/viewer` from frontend/"
      )


  def test_render_is_the_app_document_as_indented_json():
      rendered = openapi.render()
      assert json.loads(rendered) == app.openapi()
      assert rendered.endswith("}\n")


  def test_write_writes_the_rendered_document(tmp_path):
      path = tmp_path / "openapi.json"
      openapi.write(path)
      assert path.read_text() == openapi.render()
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd backend/viewer && uv run pytest ord_viewer/openapi_test.py -q
  ```

  Expected: FAIL, `ImportError: cannot import name 'openapi'`.

- [ ] **Step 3: Write the module.** `backend/viewer/ord_viewer/openapi.py`:

  ```python
  """The viewer's OpenAPI document, committed so the frontend can build types from it.

  Run ``python -m ord_viewer.openapi`` from backend/viewer to rewrite it.
  """

  import json
  import pathlib

  from ord_viewer.main import app

  # backend/viewer/openapi.json.
  DOCUMENT_PATH = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"


  def render() -> str:
      """Render the app's OpenAPI document as the committed file holds it.

      Returns:
          The document as JSON indented by two spaces, ending in a newline.
      """
      return json.dumps(app.openapi(), indent=2) + "\n"


  def write(path: pathlib.Path = DOCUMENT_PATH) -> None:
      """Write the rendered document.

      Args:
          path: Where to write it; the committed file by default.
      """
      path.write_text(render())


  if __name__ == "__main__":
      write()
  ```

- [ ] **Step 4: Write the document and run the tests.**

  ```bash
  uv run python -m ord_viewer.openapi
  uv run pytest -n auto -q 2>&1 | tail -1
  ```

  Expected: `openapi.json` exists, about 2,000 lines; every test passes. The document
  names `Query-Input` and `Query-Output` separately, since `/api/ask` returns a query as
  `/api/search` takes one.

- [ ] **Step 5: Document it and commit.** In `CLAUDE.md`'s `backend/viewer/` bullet, add:
  "`openapi.json` is the API's committed OpenAPI document, which the viewer's frontend
  generates its types from; after changing a route or model, rewrite it with
  `uv run python -m ord_viewer.openapi` (a test fails until you do)."

  ```bash
  git add backend/viewer/ord_viewer/openapi.py backend/viewer/ord_viewer/openapi_test.py \
    backend/viewer/openapi.json CLAUDE.md
  git commit -m "Commit the viewer API's OpenAPI document, pinned by a test"
  ```

### Task F2.2: The app's shell, routes, and unit-test job

**Files:**

- Create, under `frontend/apps/viewer/`: `package.json`, `index.html`, `vite.config.ts`,
  `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`, `postcss.config.cjs`,
  `public/logo.svg` (a copy of the editor's), `src/vite-env.d.ts`, `src/main.tsx`,
  `src/index.scss`, `src/App.tsx`, `src/routes.tsx`, `src/routes.test.tsx`,
  `src/components/ViewerPage.tsx`, `src/components/ViewerPage.test.tsx`,
  `src/pages/AboutPage.tsx`, `src/pages/NotFoundPage.tsx`, `src/test/setup.ts`,
  `src/test/render.tsx`
- Modify: `frontend/tsconfig.json`, `frontend/eslint.config.mjs`, `.jscpd.json`,
  `.github/workflows/ui_checks.yml`, `frontend/package-lock.json`, `CLAUDE.md`,
  `README.md`

**Interfaces:**

- Produces:
  - `#…` subpath imports for the app's own files (`"imports": {"#*": "./src/*"}`).
  - `ViewerPage({breadcrumbs, children})`: the shell every page renders in.
  - `ViewerRoutes()`: the route table F4–F6 add pages to.
  - `renderAt(path, ui)` from `#test/render.tsx`, returning Testing Library's result
    plus `history`, the paths the router went to.
  - Exported constants `EDITOR_URL` and `DOCS_URL` from `#components/ViewerPage.tsx`.

- [ ] **Step 1: The package.** `frontend/apps/viewer/package.json`:

  ```json
  {
    "name": "@open-reaction-database/viewer",
    "private": true,
    "version": "0.0.1",
    "type": "module",
    "imports": {
      "#*": "./src/*"
    },
    "scripts": {
      "dev": "vite",
      "build": "tsc -b && vite build",
      "preview": "vite preview",
      "test": "vitest",
      "test:coverage": "vitest run --coverage"
    },
    "dependencies": {
      "@buf/open-reaction-database_ord-schema.bufbuild_es": "2.16.0-00000000000000-2a4e5a8d72a2.1",
      "@bufbuild/protobuf": "^2.16.0",
      "@mantine/core": "^7.15.3",
      "@mantine/dates": "^7.15.3",
      "@mantine/form": "^7.15.3",
      "@mantine/hooks": "^7.15.3",
      "@mantine/notifications": "^7.15.3",
      "@open-reaction-database/ui": "0.0.0",
      "react": "^19.0.0",
      "react-dom": "^19.0.0",
      "wouter": "^3.3.5"
    },
    "devDependencies": {
      "@testing-library/jest-dom": "^6.9.1",
      "@testing-library/react": "^16.3.2",
      "@testing-library/user-event": "^14.6.1",
      "@types/react": "~19.2.18",
      "@types/react-dom": "~19.2.7",
      "@vitejs/plugin-react-swc": "^3.8.0",
      "@vitest/coverage-v8": "^4.1.11",
      "happy-dom": "^20.9.0",
      "postcss": "^8.5.29",
      "postcss-preset-mantine": "^1.17.0",
      "postcss-simple-vars": "^7.0.1",
      "sass": "^1.81.0",
      "vite": "^6.4.3",
      "vite-plugin-svgr": "^4.3.0",
      "vitest": "^4.1.11"
    }
  }
  ```

  The Mantine packages and the SDK are the shared package's peers. Copy
  `frontend/apps/editor/postcss.config.cjs` and `frontend/apps/editor/public/logo.svg`
  into `frontend/apps/viewer/` unchanged. Add `{ "path": "./apps/viewer" }` to
  `frontend/tsconfig.json`'s `references`, then run `npm install --ignore-scripts` from
  `frontend/`.

- [ ] **Step 2: The TypeScript projects.** `frontend/apps/viewer/tsconfig.json`:

  ```json
  {
    "files": [],
    "references": [{ "path": "./tsconfig.app.json" }, { "path": "./tsconfig.node.json" }]
  }
  ```

  `tsconfig.app.json`:

  ```json
  {
    "extends": "../../tsconfig.base.json",
    "compilerOptions": {
      "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
      "useDefineForClassFields": true,
      "lib": ["ES2023", "DOM", "DOM.Iterable"],
      "types": ["vitest/globals"],
      "jsx": "react-jsx"
    },
    "include": ["src"]
  }
  ```

  `tsconfig.node.json`:

  ```json
  {
    "extends": "../../tsconfig.base.json",
    "compilerOptions": {
      "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
      "lib": ["ES2023"]
    },
    "include": ["vite.config.ts"]
  }
  ```

  `src/vite-env.d.ts`:

  ```ts
  /// <reference types="vite/client" />
  /// <reference types="vite-plugin-svgr/client" />
  ```

- [ ] **Step 3: Vite and Vitest.** `frontend/apps/viewer/vite.config.ts`:

  ```ts
  import react from '@vitejs/plugin-react-swc';
  import svgr from 'vite-plugin-svgr';
  import { defineConfig } from 'vitest/config';

  // Where the dev server and `vite preview` send /api: the viewer's backend, served on
  // 8001 as CLAUDE.md shows. In the image, nginx proxies /api instead.
  const API_TARGET = process.env.ORD_VIEWER_API ?? 'http://127.0.0.1:8001';

  export default defineConfig({
    plugins: [react(), svgr()],
    // Ketcher, which the shared package's structure dialog loads, reads process.env.
    define: {
      'process.env': {},
    },
    // The dev server pre-bundles the dependencies it finds by crawling these entries. The
    // shared package's preview worker is listed because the crawl from index.html does not
    // follow `new Worker(...)`, and a dependency found only when the worker loads makes the
    // server reload every page.
    optimizeDeps: {
      entries: ['index.html', '../../packages/ui/src/**/*.worker.ts'],
    },
    server: { port: 5174, strictPort: true, proxy: { '/api': API_TARGET } },
    preview: { port: 4174, strictPort: true, proxy: { '/api': API_TARGET } },
    build: {
      commonjsOptions: {
        transformMixedEsModules: true,
      },
    },
    test: {
      globals: true,
      environment: 'happy-dom',
      setupFiles: ['./src/test/setup.ts'],
      // Before each test, reset every mock: its calls, and any implementation or queued
      // mock*Once value a test set. A vi.fn(impl) goes back to impl.
      mockReset: true,
      include: ['src/**/*.test.{ts,tsx}'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'text-summary', 'html', 'lcov', 'json-summary'],
        reportsDirectory: './coverage',
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/**/*.test.{ts,tsx}',
          'src/**/*.d.ts',
          'src/test/**',
          'src/main.tsx',
          // Generated, and types only.
          'src/api/schema.ts',
        ],
        // Floors at the measured coverage, rounded down.
        thresholds: {
          lines: 0,
          statements: 0,
          branches: 0,
          functions: 0,
        },
      },
    },
  });
  ```

  F2.3 Step 12 sets the floors. `src/test/setup.ts`:

  ```ts
  // Registers jest-dom's matchers (toBeInTheDocument, etc.).
  import '@testing-library/jest-dom/vitest';
  ```

- [ ] **Step 4: The page and its entry.** `frontend/apps/viewer/index.html`:

  ```html
  <!doctype html>
  <html lang="en">
    <head>
      <!-- Google tag (gtag.js), as ord-interface's pages carry it. -->
      <script
        async
        src="https://www.googletagmanager.com/gtag/js?id=G-REEDLYB0ZJ"
      ></script>
      <script>
        globalThis.dataLayer = globalThis.dataLayer || [];
        function gtag() {
          dataLayer.push(arguments);
        }
        gtag('js', new Date());
        gtag('config', 'G-REEDLYB0ZJ');
      </script>
      <meta charset="UTF-8" />
      <link
        rel="icon"
        type="image/svg+xml"
        href="/logo.svg"
      />
      <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0"
      />
      <link
        rel="preconnect"
        href="https://fonts.googleapis.com"
      />
      <link
        rel="preconnect"
        href="https://fonts.gstatic.com"
        crossorigin
      />
      <link
        href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100..900;1,100..900&display=swap"
        rel="stylesheet"
      />
      <title>Open Reaction Database</title>
    </head>
    <body>
      <div id="root"></div>
      <script
        type="module"
        src="/src/main.tsx"
      ></script>
    </body>
  </html>
  ```

  `src/index.scss`:

  ```scss
  @import '@mantine/core/styles.css';
  @import '@mantine/notifications/styles.css';
  @import '@mantine/dates/styles.css';
  ```

  `src/main.tsx`:

  ```tsx
  import { createRoot } from 'react-dom/client';
  import './index.scss';
  import '@open-reaction-database/ui/theme/global.scss';
  import { App } from '#App.tsx';

  createRoot(document.getElementById('root')!).render(<App />);
  ```

  `src/App.tsx`:

  ```tsx
  import { MantineProvider } from '@mantine/core';
  import { Notifications } from '@mantine/notifications';
  import { theme } from '@open-reaction-database/ui/theme';
  import { ViewerRoutes } from '#routes.tsx';

  export function App() {
    return (
      <MantineProvider theme={theme}>
        <ViewerRoutes />
        <Notifications position="top-right" />
      </MantineProvider>
    );
  }
  ```

- [ ] **Step 5: The test harness.** `src/test/render.tsx`:

  ```tsx
  // A test-only render helper, not an HMR boundary.
  /* eslint-disable react-refresh/only-export-components */
  import { MantineProvider } from '@mantine/core';
  import { theme } from '@open-reaction-database/ui/theme';
  import { render } from '@testing-library/react';
  import type { ReactElement } from 'react';
  import { Router } from 'wouter';
  import { memoryLocation } from 'wouter/memory-location';

  /**
   * Renders ui inside the viewer's providers, at path (which may carry a query string).
   *
   * Returns Testing Library's result and `history`, every path the router has been at,
   * oldest first; a redirect with `replace` overwrites the last.
   */
  export function renderAt(path: string, ui: ReactElement) {
    const location = memoryLocation({ path, record: true });
    const result = render(
      <MantineProvider theme={theme}>
        <Router
          hook={location.hook}
          searchHook={location.searchHook}
        >
          {ui}
        </Router>
      </MantineProvider>,
    );
    return { ...result, history: location.history };
  }
  ```

- [ ] **Step 6: Write the failing tests for the shell.**
  `src/components/ViewerPage.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { within } from '@testing-library/react';
  import { renderAt } from '#test/render.tsx';
  import { DOCS_URL, EDITOR_URL, ViewerPage } from '#components/ViewerPage.tsx';

  describe('ViewerPage', () => {
    it('links the viewer’s pages, the editor, and the docs, but not /ask', () => {
      const { getByRole, queryByRole } = renderAt(
        '/',
        <ViewerPage breadcrumbs={[]}>content</ViewerPage>,
      );
      const navigation = within(getByRole('navigation', { name: 'Main' }));
      const link = (name: string) => navigation.getByRole('link', { name });
      expect(link('Browse')).toHaveAttribute('href', '/');
      expect(link('Search')).toHaveAttribute('href', '/search');
      expect(link('Contribute')).toHaveAttribute('href', EDITOR_URL);
      expect(link('Docs')).toHaveAttribute('href', DOCS_URL);
      expect(link('About')).toHaveAttribute('href', '/about');
      expect(queryByRole('link', { name: /ask/i })).not.toBeInTheDocument();
    });

    it('renders its children', () => {
      const { getByText } = renderAt('/', <ViewerPage breadcrumbs={[]}>content</ViewerPage>);
      expect(getByText('content')).toBeInTheDocument();
    });
  });
  ```

  `src/routes.test.tsx`:

  ```tsx
  import { describe, expect, it } from 'vitest';
  import { renderAt } from '#test/render.tsx';
  import { ViewerRoutes } from '#routes.tsx';

  describe('ViewerRoutes', () => {
    it('shows About', () => {
      const { getByRole } = renderAt('/about', <ViewerRoutes />);
      expect(getByRole('heading', { name: 'About' })).toBeInTheDocument();
    });

    it('shows NotFound for a path no route takes', () => {
      const { getByRole } = renderAt('/nowhere', <ViewerRoutes />);
      expect(getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    });

    it.each([
      ['/browse', '/'],
      ['/dataset/ord_dataset-01', '/datasets/ord_dataset-01'],
      ['/id/ord-0123', '/reactions/ord-0123'],
      ['/id/a%2Fb', '/reactions/a%2Fb'],
      ['/selected-set?reaction_id=ord-b&reaction_id=ord-a', '/reactions?id=ord-b&id=ord-a'],
      ['/selected-set', '/reactions'],
    ])('redirects ord-interface’s %s to %s', (from, to) => {
      const { history } = renderAt(from, <ViewerRoutes />);
      expect(history).toEqual([to]);
    });
  });
  ```

  `history` holds one entry because each redirect replaces the path it left.

- [ ] **Step 7: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run
  ```

  Expected: FAIL, `Failed to resolve import "#components/ViewerPage.tsx"`.

- [ ] **Step 8: Write the shell.** `src/components/ViewerPage.tsx`:

  ```tsx
  import { Anchor, Group } from '@mantine/core';
  import { PageContainer, type Breadcrumbs } from '@open-reaction-database/ui/shell';
  import type { PropsWithChildren } from 'react';
  import { Link } from 'wouter';

  export const EDITOR_URL = 'https://app.open-reaction-database.org';
  export const DOCS_URL = 'https://docs.open-reaction-database.org';

  interface ViewerPageProps extends PropsWithChildren {
    breadcrumbs: Breadcrumbs;
  }

  function Navigation() {
    return (
      <nav aria-label="Main">
        <Group gap="lg">
          <Anchor
            component={Link}
            href="/"
          >
            Browse
          </Anchor>
          <Anchor
            component={Link}
            href="/search"
          >
            Search
          </Anchor>
          <Anchor href={EDITOR_URL}>Contribute</Anchor>
          <Anchor href={DOCS_URL}>Docs</Anchor>
          <Anchor
            component={Link}
            href="/about"
          >
            About
          </Anchor>
        </Group>
      </nav>
    );
  }

  /** The page shell, with the viewer's navigation in its header. */
  export function ViewerPage({ breadcrumbs, children }: Readonly<ViewerPageProps>) {
    return (
      <PageContainer
        breadcrumbs={breadcrumbs}
        headerActions={<Navigation />}
      >
        {children}
      </PageContainer>
    );
  }
  ```

- [ ] **Step 9: Write the pages.** `src/pages/NotFoundPage.tsx`:

  ```tsx
  import { Anchor, Stack, Text, Title } from '@mantine/core';
  import { Link } from 'wouter';
  import { ViewerPage } from '#components/ViewerPage.tsx';

  export function NotFoundPage() {
    return (
      <ViewerPage breadcrumbs={[]}>
        <Stack gap="sm">
          <Title order={2}>Page not found</Title>
          <Text>
            Nothing is at this address.{' '}
            <Anchor
              component={Link}
              href="/"
            >
              Browse the datasets
            </Anchor>{' '}
            instead.
          </Text>
        </Stack>
      </ViewerPage>
    );
  }
  ```

  `src/pages/AboutPage.tsx` carries ord-interface's About page
  (`app/src/views/About.tsx` at `1953940`), its text unchanged, in four sections:

  ```tsx
  import { Anchor, List, SimpleGrid, Stack, Text, Title } from '@mantine/core';
  import type { ReactNode } from 'react';
  import { ViewerPage } from '#components/ViewerPage.tsx';

  const GOVERNING_COMMITTEE = [
    'Connor Coley (MIT, C-CAS)',
    'Abby Doyle (UCLA, C-CAS)',
    'Spencer Dreher (Merck)',
    'Joel Hawkins (Pfizer)',
    'Klavs Jensen (MIT)',
    'Steven Kearnes (Genesis)',
  ];

  const ADVISORY_BOARD = [
    'Alán Aspuru-Guzik (Toronto, MADNESS)',
    'Timothy Cernak (Michigan, Entos)',
    'Lucy Colwell (Cambridge, SynTech, Google)',
    'Werngard Czechtizky (AstraZeneca)',
    'JW Feng',
    'Matthew Gaunt (Cambridge, SynTech)',
    'Alex Godfrey (NCATS Consultant)',
    'Mimi Hii (Imperial, ROAR)',
    'Greg Landrum (T5 Informatics)',
    'Fabio Lima (Novartis)',
    'Christos Nicolaou (Recursion)',
    'Sarah Reisman (Caltech, C-CAS)',
    'Francesco Rianjongdee (GSK)',
    'Marwin Segler (Microsoft)',
    'Matthew Sigman (Utah, C-CAS)',
    'Jay Stevens (BMS)',
    'Sarah Trice (XtalPi)',
    'Huimin Zhao (UIUC, MMLI)',
  ];

  const SUPPORTERS = ['Google', 'Relay Therapeutics', 'Schmidt Futures', 'University of Notre Dame'];

  const NEWS = [
    {
      title: 'A new database for machine-learning research',
      outlet: 'C&EN',
      date: '22 November 2021',
      href: 'https://cen.acs.org/physical-chemistry/computational-chemistry/new-database-machine-learning-research/99/web/2021/11',
    },
    {
      title: 'Yield-predicting AI needs chemists to stop ignoring failed experiments',
      outlet: 'Chemistry World',
      date: '12 May 2022',
      href: 'https://www.chemistryworld.com/news/yield-predicting-ai-needs-chemists-to-stop-ignoring-failed-experiments/4015662.article',
    },
    {
      title:
        'Chemists debate machine learning’s future in synthesis planning and ask for open data',
      outlet: 'C&EN',
      date: '18 May 2022',
      href: 'https://cen.acs.org/physical-chemistry/computational-chemistry/Chemists-debate-machine-learnings-future/100/i18',
    },
    {
      title: 'For chemists, the AI revolution has yet to happen',
      outlet: 'Nature',
      date: '17 May 2023',
      href: 'https://www.nature.com/articles/d41586-023-01612-x',
    },
  ];

  function Section({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
    return (
      <SimpleGrid
        cols={{ base: 1, sm: 4 }}
        spacing="lg"
      >
        <Title order={3}>{title}</Title>
        <Stack
          gap="sm"
          style={{ gridColumn: 'span 3' }}
        >
          {children}
        </Stack>
      </SimpleGrid>
    );
  }

  function Names({ names }: Readonly<{ names: Array<string> }>) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        {names.map(name => (
          <Text key={name}>{name}</Text>
        ))}
      </SimpleGrid>
    );
  }

  export function AboutPage() {
    return (
      <ViewerPage breadcrumbs={[{ title: 'About', path: '/about' }]}>
        <Stack gap="xl">
          <Section title="About">
            <Text>
              The Open Reaction Database (ORD) is an open-access schema and infrastructure
              for structuring and sharing organic reaction data, including a centralized
              data repository. The ORD schema supports conventional and emerging
              technologies, from benchtop reactions to automated high-throughput experiments
              and flow chemistry. Our vision is that a consistent data representation and
              infrastructure to support data sharing will enable downstream applications
              that will greatly improve the state of the art with respect to computer-aided
              synthesis planning, reaction prediction, and other predictive chemistry tasks.
            </Text>
            <Text>
              Since our initial meeting in October 2019, the database has grown to include
              more than 2M reactions (including a large dataset of reactions extracted from
              USPTO sources) and received contributions from academic and industrial users,
              both from published and unpublished work. Some of our current efforts include:
            </Text>
            <List>
              <List.Item>
                Improving user interfaces and providing support to contributors on GitHub
                and via email.
              </List.Item>
              <List.Item>
                Working with companies to incorporate the ORD schema into their reaction
                informatics infrastructure, including the development of
                &quot;translators&quot; between the ORD schema and electronic lab notebooks
                (ELNs).
              </List.Item>
              <List.Item>
                Engaging with journals and other stakeholders to drive adoption of the ORD
                schema as a <Anchor href="https://en.wikipedia.org/wiki/FAIR_data">FAIR</Anchor>{' '}
                data structure for sharing reaction data across academia, government, and
                industry.
              </List.Item>
            </List>
            <Text>
              <Anchor href="https://www.linkedin.com/in/benjamin-deadman-78786242/">
                Ben Deadman
              </Anchor>{' '}
              is our Reaction Data Evangelist and ORD Program Manager. Please reach out to
              him at{' '}
              <Anchor href="mailto:help@open-reaction-database.org">
                help@open‑reaction‑database.org
              </Anchor>{' '}
              for help preparing a contribution or to discuss using the ORD in your company
              or lab.
            </Text>
          </Section>
          <Section title="Publications and Media">
            <Title order={4}>Journal Articles</Title>
            <List>
              <List.Item>
                Kearnes SM, Maser MR, Wleklinski M, Kast A, Doyle AG, Dreher SD, Hawkins JM,
                Jensen KF, Coley CW. The Open Reaction Database. <em>J Am Chem Soc</em> 2021,
                143(45), 18820-18826. (
                <Anchor href="https://doi.org/10.1021/jacs.1c09820">JACS</Anchor>)
              </List.Item>
              <List.Item>
                Mercado R, Kearnes SM, Coley C. Data Sharing in Chemistry: Lessons Learned
                and a Case for Mandating Structured Reaction Data.{' '}
                <em>J Chem Inf Model</em> 2023, 63(14), 4253-4265. (
                <Anchor href="https://doi.org/10.1021/acs.jcim.3c00607">JCIM</Anchor>)
              </List.Item>
            </List>
            <Title order={4}>News</Title>
            <List>
              {NEWS.map(item => (
                <List.Item key={item.href}>
                  {item.title} (<Anchor href={item.href}>{item.outlet}</Anchor>, {item.date})
                </List.Item>
              ))}
            </List>
          </Section>
          <Section title="Leadership">
            <Title order={4}>Governing Committee</Title>
            <Names names={GOVERNING_COMMITTEE} />
            <Title order={4}>Advisory Board</Title>
            <Names names={ADVISORY_BOARD} />
          </Section>
          <Section title="Support">
            <Text>We gratefully acknowledge support from:</Text>
            <List>
              {SUPPORTERS.map(supporter => (
                <List.Item key={supporter}>{supporter}</List.Item>
              ))}
            </List>
          </Section>
        </Stack>
      </ViewerPage>
    );
  }
  ```

  The text is ord-interface's own, so its page and the viewer's read the same.

- [ ] **Step 10: Write the routes.** `src/routes.tsx`:

  ```tsx
  import { Redirect, Route, Switch, useSearchParams } from 'wouter';
  import { AboutPage } from '#pages/AboutPage.tsx';
  import { NotFoundPage } from '#pages/NotFoundPage.tsx';

  /** ord-interface's /selected-set?reaction_id=…, as the viewer's /reactions?id=…. */
  function SelectedSetRedirect() {
    const [searchParams] = useSearchParams();
    const ids = new URLSearchParams(
      searchParams.getAll('reaction_id').map(reactionId => ['id', reactionId]),
    ).toString();
    return (
      <Redirect
        to={ids ? `/reactions?${ids}` : '/reactions'}
        replace
      />
    );
  }

  /** The viewer's pages, and redirects from ord-interface's paths to theirs. */
  export function ViewerRoutes() {
    return (
      <Switch>
        <Route
          path="/about"
          component={AboutPage}
        />
        <Route path="/browse">
          <Redirect
            to="/"
            replace
          />
        </Route>
        <Route path="/dataset/:datasetId">
          {({ datasetId }) => (
            <Redirect
              to={`/datasets/${encodeURIComponent(datasetId)}`}
              replace
            />
          )}
        </Route>
        <Route path="/id/:reactionId">
          {({ reactionId }) => (
            <Redirect
              to={`/reactions/${encodeURIComponent(reactionId)}`}
              replace
            />
          )}
        </Route>
        <Route
          path="/selected-set"
          component={SelectedSetRedirect}
        />
        <Route component={NotFoundPage} />
      </Switch>
    );
  }
  ```

  wouter decodes a path parameter before handing it over, so each redirect encodes it
  again; the `/id/a%2Fb` case pins that. `/` shows NotFound until F4 adds the datasets.

- [ ] **Step 11: Run the tests to see them pass.** Same command as Step 7. Expected: 10
  passed.

- [ ] **Step 12: Lint rules and duplication scope.** In `frontend/eslint.config.mjs`,
  after the `apps/**` block, add the viewer's block. It repeats the deep-import pattern,
  since a later block's `no-restricted-imports` replaces an earlier one's for the files
  both match:

  ```js
  {
    // The viewer, like the shared package, leaves Redux, axios, and Auth0 to the editor,
    // and imports its own files through #… rather than ../.
    files: ['apps/viewer/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@open-reaction-database/ui/src/*', '**/packages/ui/*'],
              message: 'Import the shared package only through its exports.',
            },
            {
              group: ['../*'],
              message: 'Import the viewer’s files through #… instead.',
            },
            {
              group: APP_STATE_IMPORTS,
              message: 'The viewer keeps no app store and uses fetch, without sign-in.',
            },
          ],
        },
      ],
    },
  },
  ```

  In `.jscpd.json`, add `"frontend/apps/viewer/src"` to `path`. Then from `frontend/`:

  ```bash
  npm run lint:check && npm run typecheck && npm run build -w apps/viewer
  ```

  Expected: clean, and `apps/viewer/dist/` holding `index.html` and `assets/`.

- [ ] **Step 13: The CI job.** In `.github/workflows/ui_checks.yml`, narrow `test_ui`'s
  test step to the editor and the shared package:

  ```yaml
      - run: npm run test:coverage -w apps/editor -w packages/ui
  ```

  and add a job after `test_ui`:

  ```yaml
    test_ui_viewer:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
          with:
            node-version: 22
        - run: npm ci --ignore-scripts
        - run: npm run test:coverage -w apps/viewer

        - name: Coverage summary
          if: always()
          run: |
            summary="apps/viewer/coverage/coverage-summary.json"
            [ -f "$summary" ] || exit 0
            {
              echo "### UI test coverage: apps/viewer"
              echo ""
              jq -r '.total | "| Metric | % | Covered / Total |\n|---|---:|---:|\n| Lines | \(.lines.pct)% | \(.lines.covered) / \(.lines.total) |\n| Statements | \(.statements.pct)% | \(.statements.covered) / \(.statements.total) |\n| Functions | \(.functions.pct)% | \(.functions.covered) / \(.functions.total) |\n| Branches | \(.branches.pct)% | \(.branches.covered) / \(.branches.total) |"' "$summary"
            } >> "$GITHUB_STEP_SUMMARY"

        - name: Upload the viewer's coverage report
          if: always()
          uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
          with:
            name: ui-viewer-coverage
            path: frontend/apps/viewer/coverage/
            retention-days: 7
  ```

  The workflow's `pull_request` trigger already runs every job on every PR.

- [ ] **Step 14: Document and commit.** In `CLAUDE.md`:
  - the opening, after the viewer's backend: "The viewer: the public search and browse
    site over the viewer's backend; React UI on the shared package, no sign-in."
  - in `frontend/`'s layout, after `apps/editor/`: "`apps/viewer/` — the viewer: React 19,
    Vite 6, Mantine v7, wouter, and TanStack Query; no Redux, axios, or Auth0. Its own files
    import each other through `#…` subpath imports."
  - in the Frontend section: "Viewer: `npm run dev -w apps/viewer` (port 5174, sending
    `/api` to the backend on 8001 or `ORD_VIEWER_API`), `npm run build -w apps/viewer`,
    unit tests `npm test -w apps/viewer -- --run`."
  - in the CI gates' Tests line, add `test_ui_viewer`, and note that `test_ui` runs the
    editor's and the shared package's tests.

  In `README.md`, after the "Viewer backend" section, add a "Viewer" section with the
  same dev command and that `test_ui_viewer` must be added to the `main` ruleset's
  required checks. Then:

  ```bash
  git add frontend/apps/viewer frontend/tsconfig.json frontend/eslint.config.mjs \
    frontend/package-lock.json .jscpd.json .github/workflows/ui_checks.yml CLAUDE.md README.md
  git commit -m "Scaffold the viewer app: its shell, routes, and unit-test job"
  ```

### Task F2.3: The API layer and its generated types

**Files:**

- Create, under `frontend/apps/viewer/`: `scripts/generate-api.mjs`, `src/api/schema.ts`
  (generated), `src/api/types.ts`, `src/api/client.ts`, `src/api/client.test.ts`,
  `src/api/queryClient.ts`, `src/api/queryClient.test.ts`, `src/api/hooks.ts`,
  `src/api/hooks.test.tsx`, `src/api/download.ts`, `src/api/download.test.ts`
- Modify: `frontend/apps/viewer/package.json`, `src/App.tsx`, `src/test/render.tsx`,
  `vite.config.ts` (the floors), `frontend/eslint.config.mjs`, `.jscpd.json`,
  `.github/workflows/ui_checks.yml`, `frontend/package-lock.json`, `CLAUDE.md`

**Interfaces:**

- Consumes: `backend/viewer/openapi.json` (F2.1).
- Produces, for F4–F6:
  - `#api/types.ts`: `DatasetSummary`, `CompoundCount`, `CompoundSide`,
    `ReactionRecord`, `Query`, `CompiledQuery`, `ReactionsResult`, `TableResult`,
    `SearchResult`, `AskResponse`.
  - `#api/client.ts`: `class ApiError extends Error { status: number; detail: string }`;
    `getJson<T>(path, params?, signal?)`; `postJson<T>(path, body, signal?)`;
    `send(path, init?): Promise<Response>`; `errorMessage(error: unknown): string`.
  - `#api/hooks.ts`: `REACTIONS_PER_REQUEST = 100`, `useDatasets()`,
    `useDataset(datasetId)`, `useCompounds(datasetId, side)`, `useReactions(reactionIds)`,
    `useReaction(reactionId)`, `useSearch(query | null)`, `useAsk(question | null)`.
  - `#api/download.ts`: `downloadReactions(reactionIds): Promise<void>`.
  - `#api/queryClient.ts`: `createQueryClient()`, `shouldRetry(failureCount, error)`.

- [ ] **Step 1: The generator.** Add `"openapi-typescript": "^7.4.4"` and
  `"@tanstack/react-query": "^5.90.2"` (the latter to `dependencies`) to
  `frontend/apps/viewer/package.json`, and the script:

  ```json
  "generate:api": "node scripts/generate-api.mjs && prettier --write src/api/schema.ts"
  ```

  `frontend/apps/viewer/scripts/generate-api.mjs`:

  ```js
  // Writes src/api/schema.ts from the viewer backend's committed OpenAPI document.
  //
  // The license header the committed file starts with is kept: addlicense writes it once,
  // with the year the file was first committed, and regenerating must not change it.
  import { readFile, writeFile } from 'node:fs/promises';
  import openapiTS, { astToString } from 'openapi-typescript';

  const DOCUMENT = new URL('../../../../backend/viewer/openapi.json', import.meta.url);
  const OUTPUT = new URL('../src/api/schema.ts', import.meta.url);
  // A leading block comment naming a copyright, as addlicense writes it, and the blank
  // line after it. openapi-typescript's own leading comment names none.
  const LICENSE_HEADER = /^\/\*\*\n \* Copyright [\s\S]*?\n \*\/\n\n/;

  async function licenseHeader() {
    try {
      return (await readFile(OUTPUT, 'utf8')).match(LICENSE_HEADER)?.[0] ?? '';
    } catch (error) {
      if (error.code === 'ENOENT') {
        return '';
      }
      throw error;
    }
  }

  const header = await licenseHeader();
  const generated = astToString(await openapiTS(DOCUMENT));
  await writeFile(OUTPUT, header + generated);
  ```

  Run `npm install --ignore-scripts` from `frontend/`, then
  `npm run generate:api -w apps/viewer`. Commit nothing yet; Step 11 commits the file
  after addlicense has stamped it.

- [ ] **Step 2: Keep the generated file out of lint and duplication.** In
  `frontend/eslint.config.mjs`'s first block, add `'apps/viewer/src/api/schema.ts'` to
  `ignores` with the comment "Generated by `npm run generate:api -w apps/viewer`." In
  `.jscpd.json`, add `"**/api/schema.ts"` to `ignore`.

- [ ] **Step 3: The type names.** `src/api/types.ts`:

  ```ts
  import type { components, paths } from '#api/schema.ts';

  type Schemas = components['schemas'];

  export type DatasetSummary = Schemas['DatasetSummary'];
  export type CompoundCount = Schemas['CompoundCount'];
  export type ReactionRecord = Schemas['ReactionRecord'];
  /** A query as /api/search takes it. */
  export type Query = Schemas['Query-Input'];
  /** A query as /api/ask returns it: what the question compiled to. */
  export type CompiledQuery = Schemas['Query-Output'];
  export type ReactionsResult = Schemas['ReactionsResult'];
  export type TableResult = Schemas['TableResult'];
  export type SearchResult = ReactionsResult | TableResult;
  export type AskResponse = Schemas['AskResponse'];
  export type SearchRequest = Schemas['SearchRequest'];
  export type AskRequest = Schemas['AskRequest'];
  export type DownloadRequest = Schemas['DownloadRequest'];
  export type CompoundSide = NonNullable<
    NonNullable<paths['/api/datasets/{dataset_id}/compounds']['get']['parameters']['query']>['side']
  >;
  ```

- [ ] **Step 4: Write the failing tests for the client.** `src/api/client.test.ts`:

  ```ts
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import { ApiError, errorMessage, getJson, postJson } from '#api/client.ts';

  function respond(status: number, body: unknown, statusText = 'Status') {
    const text = typeof body === 'string' ? body : JSON.stringify(body);
    return vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(text, { status, statusText }));
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('getJson', () => {
    it('sends the parameters and returns the body', async () => {
      const fetch = respond(200, [{ name: 'one' }]);
      const params = new URLSearchParams([['id', 'b'], ['id', 'a']]);
      await expect(getJson('/api/reactions', params)).resolves.toEqual([{ name: 'one' }]);
      expect(fetch).toHaveBeenCalledWith('/api/reactions?id=b&id=a', expect.anything());
    });

    it('throws an ApiError carrying a message detail', async () => {
      respond(422, { detail: 'unknown path inputs.nope' });
      await expect(getJson('/api/search')).rejects.toMatchObject({
        status: 422,
        detail: 'unknown path inputs.nope',
      });
    });

    it('joins the messages of a list of validation errors', async () => {
      respond(422, {
        detail: [
          { type: 'missing', loc: ['body', 'query'], msg: 'Field required' },
          { type: 'extra_forbidden', loc: ['body', 'q'], msg: 'Extra inputs are not permitted' },
        ],
      });
      await expect(postJson('/api/search', {})).rejects.toMatchObject({
        status: 422,
        detail: 'Field required; Extra inputs are not permitted',
      });
    });

    it('falls back to the status text for a body that is not JSON', async () => {
      respond(502, '<html>Bad Gateway</html>', 'Bad Gateway');
      await expect(getJson('/api/datasets')).rejects.toMatchObject({
        status: 502,
        detail: 'Bad Gateway',
      });
    });
  });

  describe('postJson', () => {
    it('sends the body as JSON', async () => {
      const fetch = respond(200, { kind: 'reactions', reaction_ids: [], truncated: false });
      await postJson('/api/search', { query: { limit: 5 } });
      expect(fetch).toHaveBeenCalledWith(
        '/api/search',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{"query":{"limit":5}}',
        }),
      );
    });
  });

  describe('errorMessage', () => {
    it.each([
      [404, 'x', 'Not found.'],
      [422, 'unknown compound "frobnicate"', 'unknown compound "frobnicate"'],
      [429, 'x', 'Too many questions; try again in a minute.'],
      [502, 'x', 'The question could not be turned into a search.'],
      [503, 'x', 'The service is busy or unavailable; try again shortly.'],
      [504, 'x', 'The search took too long; narrow it and try again.'],
      [500, 'Internal Server Error', 'The server answered 500: Internal Server Error'],
    ])('explains a %i', (status, detail, message) => {
      expect(errorMessage(new ApiError(status, detail))).toBe(message);
    });

    it('explains a request that never reached the server', () => {
      expect(errorMessage(new TypeError('Failed to fetch'))).toBe(
        'The viewer could not reach its server.',
      );
    });
  });
  ```

- [ ] **Step 5: Run them to see them fail.**

  ```bash
  cd frontend/apps/viewer && npx vitest run src/api
  ```

  Expected: FAIL, `Failed to resolve import "#api/client.ts"`.

- [ ] **Step 6: Write the client.** `src/api/client.ts`:

  ```ts
  /** A response outside 2xx, with the server's explanation of it. */
  export class ApiError extends Error {
    readonly status: number;
    readonly detail: string;

    constructor(status: number, detail: string) {
      super(`${status}: ${detail}`);
      this.name = 'ApiError';
      this.status = status;
      this.detail = detail;
    }
  }

  /** Reads FastAPI's error body: a message, a list of validation errors, or neither. */
  async function readDetail(response: Response): Promise<string> {
    try {
      const { detail } = (await response.json()) as { detail?: unknown };
      if (typeof detail === 'string') {
        return detail;
      }
      if (Array.isArray(detail)) {
        return detail
          .map(item => (item as { msg?: unknown }).msg)
          .filter((message): message is string => typeof message === 'string')
          .join('; ');
      }
    } catch {
      // Not JSON, such as nginx's own error page.
    }
    return response.statusText;
  }

  /** Fetches path, throwing ApiError for a response outside 2xx. */
  export async function send(path: string, init?: RequestInit): Promise<Response> {
    const response = await fetch(path, init);
    if (!response.ok) {
      throw new ApiError(response.status, await readDetail(response));
    }
    return response;
  }

  export async function getJson<T>(
    path: string,
    params?: URLSearchParams,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = params ? `${path}?${params}` : path;
    return (await (await send(url, { signal })).json()) as T;
  }

  export async function postJson<T>(
    path: string,
    body: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const response = await send(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    return (await response.json()) as T;
  }

  const MESSAGES: Record<number, string> = {
    404: 'Not found.',
    429: 'Too many questions; try again in a minute.',
    502: 'The question could not be turned into a search.',
    503: 'The service is busy or unavailable; try again shortly.',
    504: 'The search took too long; narrow it and try again.',
  };

  /** What to tell the user about a failed request. */
  export function errorMessage(error: unknown): string {
    if (!(error instanceof ApiError)) {
      return 'The viewer could not reach its server.';
    }
    if (error.status === 422) {
      return error.detail;
    }
    return MESSAGES[error.status] ?? `The server answered ${error.status}: ${error.detail}`;
  }
  ```

  A 422's detail is the server's reason (a query that does not compile, a compound that
  does not resolve, a question the model declined), so it is shown as it is.

- [ ] **Step 7: Run the client's tests to see them pass.** Same command as Step 5,
  limited to `src/api/client.test.ts`. Expected: 13 passed.

- [ ] **Step 8: Write the failing tests for the cache and hooks.**
  `src/api/queryClient.test.ts`:

  ```ts
  import { describe, expect, it } from 'vitest';
  import { ApiError } from '#api/client.ts';
  import { shouldRetry } from '#api/queryClient.ts';

  describe('shouldRetry', () => {
    it('retries a request that never reached the server, once', () => {
      expect(shouldRetry(0, new TypeError('Failed to fetch'))).toBe(true);
      expect(shouldRetry(1, new TypeError('Failed to fetch'))).toBe(false);
    });

    it('never retries a request the server answered', () => {
      expect(shouldRetry(0, new ApiError(503, 'busy'))).toBe(false);
    });

    it('never retries a request refused before it was sent', () => {
      expect(shouldRetry(0, new RangeError('too many'))).toBe(false);
    });
  });
  ```

  `src/api/hooks.test.tsx`:

  ```tsx
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import { QueryClientProvider } from '@tanstack/react-query';
  import { renderHook, waitFor } from '@testing-library/react';
  import type { ReactNode } from 'react';
  import { createQueryClient } from '#api/queryClient.ts';
  import {
    REACTIONS_PER_REQUEST,
    useAsk,
    useCompounds,
    useDatasets,
    useReactions,
    useSearch,
  } from '#api/hooks.ts';

  function wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>;
  }

  function respond(body: unknown) {
    return vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body))));
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('hooks', () => {
    it('useDatasets reads /api/datasets', async () => {
      const fetch = respond([]);
      const { result } = renderHook(() => useDatasets(), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetch).toHaveBeenCalledWith('/api/datasets', expect.anything());
    });

    it('useCompounds encodes the dataset ID and names the side', async () => {
      const fetch = respond([]);
      const { result } = renderHook(() => useCompounds('a/b', 'products'), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetch).toHaveBeenCalledWith(
        '/api/datasets/a%2Fb/compounds?side=products',
        expect.anything(),
      );
    });

    it('useReactions repeats the id parameter in the order given', async () => {
      const fetch = respond([]);
      const { result } = renderHook(() => useReactions(['ord-b', 'ord-a']), { wrapper });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetch).toHaveBeenCalledWith('/api/reactions?id=ord-b&id=ord-a', expect.anything());
    });

    it('useReactions asks for nothing when given no IDs', () => {
      const fetch = respond([]);
      const { result } = renderHook(() => useReactions([]), { wrapper });
      expect(result.current.fetchStatus).toBe('idle');
      expect(fetch).not.toHaveBeenCalled();
    });

    it('useReactions refuses more IDs than one request may carry, without asking', async () => {
      const fetch = respond([]);
      const ids = Array.from({ length: REACTIONS_PER_REQUEST + 1 }, (_, index) => `ord-${index}`);
      const { result } = renderHook(() => useReactions(ids), { wrapper });
      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.error).toBeInstanceOf(RangeError);
      expect(fetch).not.toHaveBeenCalled();
    });

    it('useSearch posts the query, and waits for one', async () => {
      const fetch = respond({ kind: 'reactions', reaction_ids: [], truncated: false });
      const { result, rerender } = renderHook(({ query }) => useSearch(query), {
        wrapper,
        initialProps: { query: null as { limit: number } | null },
      });
      expect(fetch).not.toHaveBeenCalled();
      rerender({ query: { limit: 5 } });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetch).toHaveBeenCalledWith(
        '/api/search',
        expect.objectContaining({ body: '{"query":{"limit":5}}' }),
      );
    });

    it('useAsk posts the question, and waits for one', async () => {
      const fetch = respond({ query: {}, text: 'None.', result: { kind: 'reactions', reaction_ids: [], truncated: false } });
      const { result, rerender } = renderHook(({ question }) => useAsk(question), {
        wrapper,
        initialProps: { question: null as string | null },
      });
      expect(fetch).not.toHaveBeenCalled();
      rerender({ question: 'pyridine as a solvent' });
      await waitFor(() => expect(result.current.isSuccess).toBe(true));
      expect(fetch).toHaveBeenCalledWith(
        '/api/ask',
        expect.objectContaining({ body: '{"question":"pyridine as a solvent"}' }),
      );
    });
  });
  ```

  Run `npx vitest run src/api`; expected: FAIL, `Failed to resolve import
  "#api/queryClient.ts"`.

- [ ] **Step 9: Write the cache and hooks.** `src/api/queryClient.ts`:

  ```ts
  import { QueryClient } from '@tanstack/react-query';

  /**
   * Retries, once, a request that never reached the server.
   *
   * fetch rejects with a TypeError when the network fails. A response the server sent,
   * an ApiError, would be answered the same way again, and a request refused before it
   * was sent would be refused again.
   */
  export function shouldRetry(failureCount: number, error: Error): boolean {
    return error instanceof TypeError && failureCount < 1;
  }

  /** The app's cache. A corpus does not change while a page is open, so nothing goes stale. */
  export function createQueryClient(): QueryClient {
    return new QueryClient({
      defaultOptions: {
        queries: {
          retry: shouldRetry,
          staleTime: Infinity,
          refetchOnWindowFocus: false,
        },
      },
    });
  }
  ```

  `src/api/hooks.ts`:

  ```ts
  import { useQuery } from '@tanstack/react-query';
  import { getJson, postJson } from '#api/client.ts';
  import type {
    AskRequest,
    AskResponse,
    CompoundCount,
    CompoundSide,
    DatasetSummary,
    Query,
    ReactionRecord,
    SearchRequest,
    SearchResult,
  } from '#api/types.ts';

  /** The most IDs one GET /api/reactions carries, the backend's bound. */
  export const REACTIONS_PER_REQUEST = 100;

  function datasetPath(datasetId: string): string {
    return `/api/datasets/${encodeURIComponent(datasetId)}`;
  }

  export function useDatasets() {
    return useQuery({
      queryKey: ['datasets'],
      queryFn: ({ signal }) => getJson<Array<DatasetSummary>>('/api/datasets', undefined, signal),
    });
  }

  export function useDataset(datasetId: string) {
    return useQuery({
      queryKey: ['dataset', datasetId],
      queryFn: ({ signal }) => getJson<DatasetSummary>(datasetPath(datasetId), undefined, signal),
    });
  }

  /** The dataset's 30 most frequent compounds on one side, by occurrences. */
  export function useCompounds(datasetId: string, side: CompoundSide) {
    return useQuery({
      queryKey: ['compounds', datasetId, side],
      queryFn: ({ signal }) =>
        getJson<Array<CompoundCount>>(
          `${datasetPath(datasetId)}/compounds`,
          new URLSearchParams({ side }),
          signal,
        ),
    });
  }

  /** The reactions with these IDs, in order, one request for at most 100. */
  export function useReactions(reactionIds: ReadonlyArray<string>) {
    return useQuery({
      queryKey: ['reactions', reactionIds],
      queryFn: ({ signal }) => {
        if (reactionIds.length > REACTIONS_PER_REQUEST) {
          throw new RangeError(
            `${reactionIds.length} reaction IDs; one request takes at most ${REACTIONS_PER_REQUEST}`,
          );
        }
        const params = new URLSearchParams(reactionIds.map(reactionId => ['id', reactionId]));
        return getJson<Array<ReactionRecord>>('/api/reactions', params, signal);
      },
      enabled: reactionIds.length > 0,
    });
  }

  export function useReaction(reactionId: string) {
    return useQuery({
      queryKey: ['reaction', reactionId],
      queryFn: ({ signal }) =>
        getJson<ReactionRecord>(
          `/api/reactions/${encodeURIComponent(reactionId)}`,
          undefined,
          signal,
        ),
    });
  }

  /** Runs the query, or nothing while it is null. */
  export function useSearch(query: Query | null) {
    return useQuery({
      queryKey: ['search', query],
      queryFn: ({ signal }) =>
        postJson<SearchResult>('/api/search', { query } as SearchRequest, signal),
      enabled: query !== null,
    });
  }

  /** Asks the question, or nothing while it is null. */
  export function useAsk(question: string | null) {
    return useQuery({
      queryKey: ['ask', question],
      queryFn: ({ signal }) =>
        postJson<AskResponse>('/api/ask', { question } as AskRequest, signal),
      enabled: question !== null,
    });
  }
  ```

  The request bodies are cast rather than checked with `satisfies` because `enabled`
  keeps `null` from reaching them, which the types cannot see.

- [ ] **Step 10: Write the download, test first.** `src/api/download.test.ts`:

  ```ts
  import { afterEach, describe, expect, it, vi } from 'vitest';
  import { downloadReactions } from '#api/download.ts';

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('downloadReactions', () => {
    it('posts the IDs and saves the file under the server’s name', async () => {
      const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(new Blob(['gzip']), {
          headers: { 'Content-Disposition': 'attachment; filename="ord-search-results.pb.gz"' },
        }),
      );
      vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:viewer');
      vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined);
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockReturnValue(undefined);

      await downloadReactions(['ord-a', 'ord-b']);

      expect(fetch).toHaveBeenCalledWith(
        '/api/download',
        expect.objectContaining({ body: '{"reaction_ids":["ord-a","ord-b"]}' }),
      );
      const link = click.mock.contexts[0] as HTMLAnchorElement;
      expect(link.download).toBe('ord-search-results.pb.gz');
      expect(link.href).toBe('blob:viewer');
    });

    it('throws the server’s error rather than saving it', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ detail: 'No known reaction' }), { status: 404 }),
      );
      await expect(downloadReactions(['ord-x'])).rejects.toMatchObject({
        status: 404,
        detail: 'No known reaction',
      });
    });
  });
  ```

  `src/api/download.ts`:

  ```ts
  import { send } from '#api/client.ts';
  import type { DownloadRequest } from '#api/types.ts';

  const DEFAULT_FILE_NAME = 'ord-search-results.pb.gz';

  function fileName(disposition: string | null): string {
    return /filename="([^"]+)"/.exec(disposition ?? '')?.[1] ?? DEFAULT_FILE_NAME;
  }

  /** Saves the reactions as one gzipped ord.Dataset, named as the server names it. */
  export async function downloadReactions(reactionIds: ReadonlyArray<string>): Promise<void> {
    const body: DownloadRequest = { reaction_ids: [...reactionIds] };
    const response = await send('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName(response.headers.get('Content-Disposition'));
    link.click();
    // The browser has taken the file once the click's task ends.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  ```

- [ ] **Step 11: Provide the cache, run everything, and commit.** In `src/App.tsx`, wrap
  `<ViewerRoutes />` and `<Notifications />` in
  `<QueryClientProvider client={queryClient}>`, where
  `const [queryClient] = useState(createQueryClient);` at the top of `App`. In
  `src/test/render.tsx`, wrap the `Router` in
  `<QueryClientProvider client={createQueryClient()}>` the same way. Then:

  ```bash
  cd frontend/apps/viewer && npx vitest run 2>&1 | tail -3
  ```

  Expected: every test passes, 35 in all. Then stamp the generated file's license header
  with the repository's own hook, and confirm that regenerating keeps it. From the
  worktree's root:

  ```bash
  uvx pre-commit run addlicense --files frontend/apps/viewer/src/api/schema.ts
  head -3 frontend/apps/viewer/src/api/schema.ts
  git add frontend/apps/viewer/src/api/schema.ts
  (cd frontend && npm run generate:api -w apps/viewer)
  git diff --exit-code -- frontend/apps/viewer/src/api/schema.ts
  ```

  Expected: the hook reports that it modified the file (its exit status is 1 for that
  reason), the head shows the Apache header, and the diff after regenerating is empty.

- [ ] **Step 12: Set the coverage floors.** Run `npx vitest run --coverage` in
  `frontend/apps/viewer`, and in `vite.config.ts` set each threshold to the measured
  percentage rounded down to an integer.

- [ ] **Step 13: Check the types in CI.** In `.github/workflows/ui_checks.yml`'s
  `lint_and_build_ui`, after `npm run typecheck`, add:

  ```yaml
        # The viewer's API types are generated from backend/viewer/openapi.json, which
        # test_python_viewer pins to the backend's routes.
        - name: The viewer's API types match the backend's document
          run: |
            npm run generate:api -w apps/viewer
            git diff --exit-code -- apps/viewer/src/api/schema.ts
  ```

  Check that it bites: change a description in `backend/viewer/openapi.json`, run the
  two lines from `frontend/`, expect a non-zero exit, and restore the file.

- [ ] **Step 14: Document and commit.** In `CLAUDE.md`'s `apps/viewer/` bullet, add:
  "Its API types (`src/api/schema.ts`) are generated from `backend/viewer/openapi.json`
  with `npm run generate:api -w apps/viewer`, after `python -m ord_viewer.openapi`;
  `lint_and_build_ui` fails when they differ."

  ```bash
  (cd frontend && npm run lint:check && npm run typecheck && npm run build -w apps/viewer)
  git add frontend/apps/viewer frontend/eslint.config.mjs frontend/package-lock.json \
    .jscpd.json .github/workflows/ui_checks.yml CLAUDE.md
  git commit -m "Read the viewer's API through TanStack Query with generated types"
  ```

### Task F2.4: Open the PR

- [ ] **Step 1:** Run `uvx pre-commit run --all-files`, push, and open the PR titled
  "Scaffold the viewer app with its typed API client". Its Notes say that
  `test_ui_viewer` must be added to the `main` ruleset's required checks, and that `/`
  shows NotFound until F4.
- [ ] **Step 2:** Run `review-pr` on it.

---

## PR F3: the viewer's image, and the root's single-app files

Branch `viewer-image`, in its own worktree from `origin/main`.

### Task F3.1: Deriving the fixture corpus from the command line

**Files:**

- Modify: `backend/viewer/ord_viewer/testing.py`
- Create: `backend/viewer/ord_viewer/testing_test.py`

**Interfaces:**

- Produces: `python -m ord_viewer.testing <directory>`, run from `backend/viewer` in the
  dev environment: derives the test corpus into an empty or missing directory. The
  fixture's reaction IDs, such as `ord-viewer0101`, are what the smoke test fetches.

- [ ] **Step 1: Write the failing tests.** `backend/viewer/ord_viewer/testing_test.py`:

  ```python
  """The command that derives the test corpus for the image's smoke test."""

  import pytest

  from ord_viewer.testing import main, make_client


  def test_main_derives_a_corpus_the_app_serves(tmp_path):
      main([str(tmp_path / "corpus")])
      with make_client(tmp_path / "corpus") as client:
          assert client.get("/api/reactions/ord-viewer0101").status_code == 200


  def test_main_derives_into_an_empty_directory_that_exists(tmp_path):
      main([str(tmp_path)])
      assert (tmp_path / "pivots").is_dir()


  def test_main_refuses_a_directory_that_holds_files(tmp_path):
      (tmp_path / "notes.txt").write_text("")
      with pytest.raises(ValueError, match="is not empty"):
          main([str(tmp_path)])
  ```

- [ ] **Step 2: Run them to see them fail.**

  ```bash
  cd backend/viewer && uv run pytest ord_viewer/testing_test.py -q
  ```

  Expected: FAIL, `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Add `main`.** In `ord_viewer/testing.py`, add `import argparse` to the
  imports, and at the end of the module:

  ```python
  def main(argv: Sequence[str] | None = None) -> None:
      """Derive the test corpus into a directory, for the image's smoke test.

      Args:
          argv: The command line's arguments, naming the directory; None reads sys.argv.
              The directory may be missing, and is created.

      Raises:
          ValueError: If the directory exists and holds anything.
      """
      parser = argparse.ArgumentParser(description="Derive the viewer's test corpus.")
      parser.add_argument("directory", type=pathlib.Path)
      root = parser.parse_args(argv).directory
      if root.exists() and any(root.iterdir()):
          raise ValueError(f"{root} is not empty")
      root.mkdir(parents=True, exist_ok=True)
      derive_corpus(root)


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: Run the suite, then commit.**

  ```bash
  uv run pytest -n auto -q 2>&1 | tail -1
  uv run ruff check ord_viewer && uv run ruff format --check ord_viewer && uv run ty check ord_viewer
  git add ord_viewer/testing.py ord_viewer/testing_test.py
  git commit -m "Derive the viewer's test corpus from the command line"
  ```

### Task F3.2: The viewer's image

**Files:**

- Create: `deploy/viewer/Dockerfile`, `deploy/viewer/Dockerfile.dockerignore`,
  `deploy/viewer/nginx.conf`, `deploy/viewer/supervisord.conf`,
  `deploy/viewer/exit_on_failure.sh`, `deploy/viewer/smoke_test.sh`

**Interfaces:**

- Produces: an image listening on 8080 that reads `ORD_VIEWER_CORPUS_DIR` and the other
  `ORD_VIEWER_*` settings at run time; `deploy/viewer/smoke_test.sh <base URL> <reaction
  ID>`, which F3.3's job runs.

- [ ] **Step 1: The build context.** `deploy/viewer/Dockerfile.dockerignore` lists what
  the image may read and nothing else:

  ```text
  # Everything is left out except what the Dockerfile copies.
  *
  !backend/viewer/pyproject.toml
  !backend/viewer/uv.lock
  !backend/viewer/ord_viewer/
  !deploy/viewer/nginx.conf
  !deploy/viewer/supervisord.conf
  !deploy/viewer/exit_on_failure.sh
  # npm ci installs every workspace the lockfile names, so all of frontend/ is in.
  !frontend/

  # Within those: local installs and builds, and the test suite.
  **/node_modules/
  **/__pycache__/
  frontend/**/dist/
  frontend/**/coverage/
  frontend/**/playwright-report/
  frontend/**/test-results/
  **/*_test.py
  **/conftest.py
  backend/viewer/ord_viewer/testing.py
  ```

  `testing.py` imports FastAPI's `TestClient`, a dev dependency, and nothing in the app
  imports it.

- [ ] **Step 2: The Dockerfile.** `deploy/viewer/Dockerfile`, with the three images'
  digests copied from `deploy/editor/Dockerfile`:

  ```dockerfile
  # The viewer: its SPA and API behind nginx, under supervisord. The corpus is mounted at
  # run time and named by ORD_VIEWER_CORPUS_DIR. Built from the repository's root:
  #   docker build -f deploy/viewer/Dockerfile .

  FROM ghcr.io/astral-sh/uv:0.13.0@sha256:<the editor's digest> AS uv

  FROM node:22-alpine@sha256:<the editor's digest> AS spa
  WORKDIR /app
  # The manifests first, so npm ci's layer stays cached until one of them changes. Every
  # workspace the lockfile names is listed; npm ci fails if one is missing.
  COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
  COPY frontend/apps/editor/package.json apps/editor/
  COPY frontend/apps/viewer/package.json apps/viewer/
  COPY frontend/packages/ui/package.json packages/ui/
  RUN npm ci --ignore-scripts
  COPY frontend/ ./
  RUN npm run build -w apps/viewer

  FROM python:3.12-slim@sha256:<the editor's digest>
  RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor && \
      apt-get clean && rm -rf /var/lib/apt/lists/* && \
      groupadd --gid 1001 appgroup && \
      useradd --uid 1001 --gid 1001 --create-home --shell /usr/sbin/nologin appuser
  COPY --from=uv /uv /bin/
  ENV UV_PROJECT_ENVIRONMENT=/usr/local \
      UV_COMPILE_BYTECODE=1 \
      UV_LINK_MODE=copy
  WORKDIR /app
  # The lockfile first, so the dependencies' layer stays cached until it changes.
  COPY backend/viewer/pyproject.toml backend/viewer/uv.lock ./
  RUN uv sync --frozen --no-dev --no-build
  COPY backend/viewer/ord_viewer/ ./ord_viewer/
  COPY --from=spa /app/apps/viewer/dist /var/www/html
  COPY deploy/viewer/nginx.conf /etc/nginx/nginx.conf
  COPY deploy/viewer/supervisord.conf /etc/supervisor/viewer.conf
  COPY deploy/viewer/exit_on_failure.sh /usr/local/bin/exit_on_failure.sh
  # nginx keeps its temporary files under /var/lib/nginx, and DuckDB may spill into /app.
  RUN chmod +x /usr/local/bin/exit_on_failure.sh && \
      chown -R appuser:appgroup /app /var/lib/nginx /var/log/nginx
  USER appuser
  EXPOSE 8080
  ARG GIT_COMMIT=unknown
  LABEL org.opencontainers.image.revision=$GIT_COMMIT
  CMD ["supervisord", "-c", "/etc/supervisor/viewer.conf"]
  ```

  Replace each `<the editor's digest>` with the `sha256:` value on the same image's
  `FROM` line in `deploy/editor/Dockerfile`; they are index digests, so they cover
  arm64.

- [ ] **Step 3: supervisord.** `deploy/viewer/supervisord.conf`:

  ```ini
  ; Runs the API and nginx as appuser. Neither restarts: when either exits, the listener
  ; stops supervisord and with it the container, so a backend that cannot open its corpus
  ; fails the task where it can be seen, rather than leaving nginx answering 502.
  [supervisord]
  nodaemon=true
  logfile=/dev/null
  logfile_maxbytes=0
  pidfile=/tmp/supervisord.pid

  [program:api]
  command=uvicorn ord_viewer.main:app --host 127.0.0.1 --port 8000 --workers 1
  directory=/app
  autorestart=false
  startsecs=0
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  stderr_logfile=/dev/stderr
  stderr_logfile_maxbytes=0

  [program:nginx]
  command=nginx -g 'daemon off;'
  autorestart=false
  startsecs=0
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  stderr_logfile=/dev/stderr
  stderr_logfile_maxbytes=0

  [eventlistener:exit_on_failure]
  command=/usr/local/bin/exit_on_failure.sh
  events=PROCESS_STATE_EXITED,PROCESS_STATE_FATAL
  ```

  `deploy/viewer/exit_on_failure.sh`:

  ```sh
  #!/bin/sh
  # A supervisord event listener: on the first event it is sent, a program's exit, it
  # stops supervisord, which stops the other program and exits.
  printf 'READY\n'
  read -r _header
  kill -TERM "$PPID"
  ```

  A stop that supervisord itself begins, on the container's SIGTERM, moves its programs
  to STOPPED rather than EXITED, so it sends the listener nothing.

- [ ] **Step 4: nginx.** `deploy/viewer/nginx.conf`:

  ```nginx
  # nginx runs as appuser, so it keeps its pid in /tmp and logs to the container's output.
  pid /tmp/nginx.pid;
  error_log stderr warn;

  events {}

  http {
      include /etc/nginx/mime.types;
      default_type application/octet-stream;
      access_log /dev/stdout;
      sendfile on;

      gzip on;
      gzip_comp_level 6;
      gzip_min_length 1024;
      gzip_proxied any;
      gzip_vary on;
      gzip_types text/plain text/css text/javascript application/javascript application/json application/wasm image/svg+xml;

      # Behind the load balancer, $remote_addr is the balancer's. These restore the
      # client's from X-Forwarded-For, trusting the hops inside the VPC's private range, so
      # the limit below counts each client rather than each balancer node.
      set_real_ip_from 10.0.0.0/8;
      real_ip_header X-Forwarded-For;
      real_ip_recursive on;

      # Each ask costs model calls; 10 a minute per client, with a burst of 5.
      limit_req_zone $binary_remote_addr zone=ask:10m rate=10r/m;
      limit_req_status 429;

      # A download of 1,000 IDs is about 40 KiB.
      client_max_body_size 128k;

      # The SPA's hashed assets never change; index.html, which names them, always might.
      map $uri $cache_control {
          default "";
          ~^/assets/ "public, max-age=31536000, immutable";
          /index.html "no-cache";
      }

      upstream api {
          server 127.0.0.1:8000;
      }

      server {
          listen 8080;
          root /var/www/html;

          proxy_set_header Host $host;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;

          # Past the slot wait, two 30 s model calls, and the 60 s search.
          location = /api/ask {
              limit_req zone=ask burst=5 nodelay;
              proxy_read_timeout 150s;
              proxy_pass http://api;
          }

          # Ahead of every static rule, so none shadows /api/openapi.json. Past the 10 s slot
          # wait and the 30 s search timeout.
          location ^~ /api/ {
              proxy_read_timeout 60s;
              proxy_pass http://api;
          }

          location ~ ^/editor(/|$) {
              return 301 https://app.open-reaction-database.org/;
          }

          location / {
              add_header Cache-Control $cache_control;
              try_files $uri /index.html;
          }
      }
  }
  ```

- [ ] **Step 5: The smoke test.** `deploy/viewer/smoke_test.sh`:

  ```bash
  #!/usr/bin/env bash
  # Checks a running viewer image through nginx: the API, the SPA, and the routing,
  # caching, and limits between them.
  #
  # Usage: deploy/viewer/smoke_test.sh <base URL> <reaction ID in its corpus>
  set -euo pipefail

  base=${1:?usage: smoke_test.sh <base URL> <reaction ID>}
  reaction=${2:?usage: smoke_test.sh <base URL> <reaction ID>}

  status() {
    curl -s -o /dev/null -w '%{http_code}' "$@"
  }

  expect_status() {
    local expected=$1
    shift
    local actual
    actual=$(status "$@")
    if [[ $actual != "$expected" ]]; then
      echo "expected $expected, got $actual: $*" >&2
      exit 1
    fi
  }

  # The backend opens its corpus before it accepts connections; nginx answers 502 until then.
  for _ in $(seq 1 90); do
    [[ $(status "$base/api/health") == 200 ]] && break
    sleep 2
  done
  expect_status 200 "$base/api/health"

  # The SPA, at its root and at a deep link, which falls back to index.html.
  curl -sf "$base/" | grep -q '<div id="root">'
  curl -sf "$base/reactions/$reaction" | grep -q '<div id="root">'
  curl -sfI "$base/" | grep -qi '^cache-control: no-cache'
  asset=$(curl -sf "$base/" | grep -oE '/assets/[^"]+\.js' | head -1)
  curl -sfI "$base$asset" | grep -qi '^cache-control: public, max-age=31536000, immutable'

  # The API, ahead of the static rules.
  curl -sf "$base/api/openapi.json" | grep -q '"/api/search"'
  expect_status 200 "$base/api/reactions/$reaction"
  expect_status 301 "$base/editor"

  # With no key set, an ask is refused by the backend, then by nginx past its burst.
  ask=(-X POST -H 'Content-Type: application/json' -d '{"question": "pyridine"}' "$base/api/ask")
  expect_status 503 "${ask[@]}"
  limited=0
  for _ in $(seq 1 10); do
    [[ $(status "${ask[@]}") == 429 ]] && limited=$((limited + 1))
  done
  if ((limited == 0)); then
    echo "expected some of 10 quick asks to be limited" >&2
    exit 1
  fi

  # A body past 128 KiB never reaches the backend.
  head -c 200000 /dev/zero | tr '\0' 'a' >"${TMPDIR:-/tmp}/viewer-large-body"
  expect_status 413 -X POST -H 'Content-Type: application/json' \
    --data-binary "@${TMPDIR:-/tmp}/viewer-large-body" "$base/api/download"

  echo "the viewer's image passed its smoke test"
  ```

- [ ] **Step 6: Build and check it locally.** From the worktree's root, with Docker
  running:

  ```bash
  docker buildx build --platform linux/arm64 --load -t ord-viewer:local \
    -f deploy/viewer/Dockerfile .
  corpus=$(mktemp -d)/corpus
  (cd backend/viewer && uv run python -m ord_viewer.testing "$corpus")
  docker run -d --name viewer-local -p 8080:8080 -v "$corpus:/corpus:ro" \
    -e ORD_VIEWER_CORPUS_DIR=/corpus ord-viewer:local
  deploy/viewer/smoke_test.sh http://127.0.0.1:8080 ord-viewer0101
  docker rm -f viewer-local
  ```

  Expected: "the viewer's image passed its smoke test". On an amd64 machine, build with
  `--platform linux/amd64` instead; CI builds arm64 natively. If uvicorn fails on a
  missing shared library, add its Debian package to the `apt-get install` line and say
  so in the PR.

  Then check that a corpus that cannot open stops the container:

  ```bash
  docker run -d --name viewer-empty -v "$(mktemp -d):/corpus:ro" \
    -e ORD_VIEWER_CORPUS_DIR=/corpus ord-viewer:local
  timeout 90 docker wait viewer-empty
  docker logs viewer-empty 2>&1 | grep -qE 'no [a-z]+/ directory'
  docker rm viewer-empty
  ```

  Expected: `docker wait` prints an exit code within 90 s, and the log names the missing
  tree. Check that the listener is what stops it: delete the `[eventlistener:…]` section,
  rebuild, and expect `timeout` to exit 124 with the container still up; then restore it.

- [ ] **Step 7: Commit.**

  ```bash
  git add deploy/viewer
  git commit -m "Build the viewer's image: its SPA and API behind nginx"
  ```

### Task F3.3: One image job per app

**Files:**

- Create: `.github/workflows/images.yml`
- Modify: `.github/dependabot.yml`

- [ ] **Step 1: The workflow.** `.github/workflows/images.yml`:

  ```yaml
  name: Images

  on:
    # Every pull request runs these jobs, whatever it changes: the main branch's ruleset
    # requires them, and a required check that never reports leaves the PR blocked.
    pull_request:
      branches:
        - '*'
    push:
      branches:
        - 'main'

  # Both images are built for the platform the web services run on, on runners of that
  # platform, so nothing is emulated. Layers are cached in the Actions cache, one scope per
  # image, so a change that touches neither lockfile rebuilds only the source layers.
  jobs:
    build_editor_image:
      runs-on: ubuntu-24.04-arm
      steps:
        - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
        - name: Build the editor's image
          uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
          with:
            context: .
            file: deploy/editor/Dockerfile
            platforms: linux/arm64
            push: false
            # The bundle will not build without the Auth0 settings. These are placeholders,
            # and the image is never pushed.
            build-args: |
              VITE_AUTH0_DOMAIN=auth0.example.com
              VITE_AUTH0_CLIENT_ID=placeholder
              VITE_AUTH0_AUDIENCE=https://auth0.example.com/api/v2/
              VITE_AUTH0_ISSUER=https://auth0.example.com/
              VITE_AUTH0_SCOPE=openid
            cache-from: type=gha,scope=editor
            cache-to: type=gha,mode=max,scope=editor

    build_viewer_image:
      runs-on: ubuntu-24.04-arm
      steps:
        - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
        - name: Build the viewer's image
          uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
          with:
            context: .
            file: deploy/viewer/Dockerfile
            platforms: linux/arm64
            push: false
            load: true
            tags: ord-viewer:ci
            cache-from: type=gha,scope=viewer
            cache-to: type=gha,mode=max,scope=viewer

        - name: Install uv
          uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
          with:
            python-version: "3.12"

        - name: Derive the test corpus
          working-directory: backend/viewer
          run: |
            uv sync --frozen --no-build
            uv run --frozen --no-build python -m ord_viewer.testing "$RUNNER_TEMP/corpus"

        - name: Serve the image over the test corpus
          run: |
            docker run -d --name viewer -p 8080:8080 \
              -v "$RUNNER_TEMP/corpus:/corpus:ro" -e ORD_VIEWER_CORPUS_DIR=/corpus \
              ord-viewer:ci

        - name: Check the image through nginx
          run: deploy/viewer/smoke_test.sh http://127.0.0.1:8080 ord-viewer0101

        - name: A corpus that cannot open stops the container
          run: |
            empty=$(mktemp -d)
            docker run -d --name viewer-empty -v "$empty:/corpus:ro" \
              -e ORD_VIEWER_CORPUS_DIR=/corpus ord-viewer:ci
            timeout 90 docker wait viewer-empty
            docker logs viewer-empty 2>&1 | grep -qE 'no [a-z]+/ directory'

        - name: Container logs (on failure)
          if: failure()
          run: |
            docker logs viewer || true
            docker logs viewer-empty || true
  ```

- [ ] **Step 2: Dependabot.** In `.github/dependabot.yml`, add `- /deploy/viewer` to the
  `docker` entry's `directories`.

- [ ] **Step 3: Lint the workflow, then commit.** Run `actionlint` if it is installed;
  otherwise read the YAML once more against `ui_checks.yml`'s shape.

  ```bash
  git add .github/workflows/images.yml .github/dependabot.yml
  git commit -m "Build each app's image in CI, and smoke-test the viewer's"
  ```

### Task F3.4: Root files move to the app or language they serve

**Files:**

- Move: `docker-compose.yml` → `backend/editor/docker-compose.yml`; `ruff.toml` →
  `backend/ruff.toml`
- Delete: `Makefile`
- Modify: `.github/dependabot.yml`, `deploy/editor/Dockerfile.dockerignore`,
  `CLAUDE.md`, `README.md`, `scripts/dev-e2e.sh`,
  `frontend/apps/editor/UI_Generated_Documentation.md`, and, with the user's leave,
  `.claude/skills/ord-app-ui-testing/SKILL.md`

- [ ] **Step 1: Move the compose file.**

  ```bash
  git mv docker-compose.yml backend/editor/docker-compose.yml
  ```

  In it, below the license header, add:

  ```yaml
  # The editor's development stack: Postgres, the API, and a migration job. Run it from
  # this directory: docker compose up -d. The project keeps the name it had at the
  # repository's root, and with it the name of the pgdata volume.
  name: ord-app
  ```

  and change the paths, which are relative to this directory now: `build.context`
  from `backend/editor` to `.`, and each `./backend/editor:/app` volume to `.:/app`.
  Check it:

  ```bash
  (cd backend/editor && docker compose config --quiet && docker compose up -d db)
  docker volume ls --format '{{.Name}}' | grep -x 'ord-app_pgdata'
  (cd backend/editor && docker compose down)
  ```

  Expected: the volume is `ord-app_pgdata`, the one the root's file made.

- [ ] **Step 2: Move ruff's configuration.**

  ```bash
  git mv ruff.toml backend/ruff.toml
  ```

  In it, change the opening comment to "One ruff configuration for every Python project
  under backend/. The projects' pyproject.toml files carry no [tool.ruff] table, so ruff
  finds this file from any of them." and `src` to `["editor", "viewer"]`, which ruff
  resolves against this file's directory. Check that both projects still use it and
  still sort their own packages as first-party:

  ```bash
  uvx pre-commit run ruff --all-files && uvx pre-commit run ruff-format --all-files
  (cd backend/editor && uv run ruff check --show-settings ord_editor/__init__.py | grep -A3 '^linter.src')
  ```

  Expected: both hooks pass with no changes, and `linter.src` lists
  `…/backend/editor` and `…/backend/viewer`.

- [ ] **Step 3: Delete the Makefile.**

  ```bash
  git rm Makefile
  ```

  Every target's tool runs in pre-commit: `ruff`, `ruff-format`, `ty-editor`,
  `ty-viewer`, and `jscpd`.

- [ ] **Step 4: Follow the moves.**
  - `.github/dependabot.yml`: the `docker-compose` entry's `directory` becomes
    `/backend/editor`, and its comment names `backend/editor/docker-compose.yml`.
  - `deploy/editor/Dockerfile.dockerignore`: replace `docker-compose.yml` with
    `backend/editor/docker-compose.yml`, and delete `Makefile`.
  - `README.md`: under "docker-compose", the command becomes
    `cd backend/editor && docker compose up -d`; line 26's "the docker-compose database"
    stays true.
  - `scripts/dev-e2e.sh`: the comment's command becomes
    `` `docker compose up -d` in backend/editor ``.
  - `frontend/apps/editor/UI_Generated_Documentation.md` line 127:
    `cd backend/editor && docker compose up -d`.
  - `CLAUDE.md`: the `backend/editor/` bullet adds "`docker-compose.yml` (Postgres, the
    API, and a migration job, for development)"; the root bullet becomes "`backend/ruff.toml`
    — the ruff config for every Python project. `scripts/` — dev/E2E helpers."; the Lint
    line says "config in `backend/ruff.toml`"; the Checks line's "also `make duplication`"
    becomes "also `uvx pre-commit run jscpd --all-files`"; the layout gains
    "`deploy/viewer/` — the viewer's image: its SPA and API behind nginx under
    supervisord, for `linux/arm64`; the corpus is mounted at run time"; and the CI gates
    gain an **Images** line: "`build_editor_image`, and `build_viewer_image` with its
    smoke test through nginx."
  - `.claude/skills/ord-app-ui-testing/SKILL.md` lines 112, 113, and 131: the compose
    commands run in `backend/editor`. The file is write-protected in the sandbox; ask
    the user before editing it, and list it in the PR's Notes if they would rather
    edit it themselves.

  Then confirm nothing names the old paths:

  ```bash
  git grep -nE '(^|[^/])docker-compose\.yml|make (duplication|check-ruff|python-)|root `ruff\.toml`'
  ```

  Expected: only the lines this step wrote, which name the new paths.

- [ ] **Step 5: Commit.**

  ```bash
  git add backend/editor/docker-compose.yml backend/ruff.toml docker-compose.yml ruff.toml \
    Makefile .github/dependabot.yml deploy/editor/Dockerfile.dockerignore CLAUDE.md \
    README.md scripts/dev-e2e.sh frontend/apps/editor/UI_Generated_Documentation.md
  git status --short   # the moves, the deletion, and the files listed above, nothing else
  git commit -m "Move the editor's compose file and ruff's config under backend/"
  ```

### Task F3.5: Open the PR

- [ ] **Step 1:** Run `uvx pre-commit run --all-files`, push, and open the PR titled
  "Build the viewer's image, and an image job per app". Its Notes say:
  `build_editor_image` and `build_viewer_image` must be added to the `main` ruleset's
  required checks; the compose file now runs from `backend/editor`, keeping the project
  name `ord-app`; and the image needs nothing at build time but the repository.
- [ ] **Step 2:** Run `review-pr` on it. Read the first run's timings in the Actions log
  and record the cold and cached build times in the PR body.

## After F3

- Write F4–F6's plan, against the hooks, `renderAt`, `routeParam`, and the image F2 and
  F3 shipped.
- Where F1–F3 departed from these tasks is recorded under
  [Refinements](#refinements-to-the-design), and the design matches.
