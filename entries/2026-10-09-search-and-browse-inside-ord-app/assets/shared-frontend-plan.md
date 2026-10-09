# Shared frontend package: implementation plan for W1, W2, and A

- **Date:** 2026-10-09
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** ready to execute once ord-app#837 merges
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ord-app's `ui/` into an npm workspace at `frontend/` (PR W1), start the
shared package `@open-reaction-database/ui` with the theme and the display primitives
(PR W2), and add the `ReactionProvider` that later steps move the reaction view onto
(PR A).

**Architecture:** W1 moves files and tooling configuration and changes no source. W2
creates `frontend/packages/ui`, consumed as TypeScript source through its `exports` map,
and points the editor's imports at it. A adds the provider, its hooks, and two sources
(the editor's Redux store, and a plain object) in the editor, wires the reaction and
template pages to it, and adds Playwright coverage of the reaction page. The provider
keeps supplying the old `reactionContext`, so no component changes until step B.

**Tech Stack:** npm workspaces, React 19, Mantine 7, Redux Toolkit, Vite 6, Vitest 4
(happy-dom), Playwright, TypeScript 5.6 project references, ESLint 9 flat config,
`use-sync-external-store`, `eslint-plugin-import-x`.

**Spec:** [`shared-frontend-design.md`](shared-frontend-design.md), beside this file.
Read it first. Where this plan refines it, the [Refinements](#refinements-to-the-design)
section says how, and the design has been updated to match.

## Global Constraints

- Repository: `open-reaction-database/ord-app`, local checkout `~/ord/ord-app`. Every PR
  starts from an up-to-date `main` on its own branch. Never commit to `main`; never
  force-push.
- Precondition: [ord-app#837](https://github.com/open-reaction-database/ord-app/pull/837)
  (protobuf-es) is merged. Land or rebase the other open UI PRs before W1 where
  practical.
- Each PR leaves the editor's behavior unchanged, except where a task says otherwise.
  Existing test assertions stay as they are; only render harnesses and import paths
  change.
- CI job names stay `lint_and_build_ui`, `test_ui`, `test_e2e`, `check_duplication`.
- Every new `.ts`, `.tsx`, `.scss`, `.mjs`, and `.cjs` file starts with the Apache-2.0
  header used across the repository, copyright 2026, "Open Reaction Database Project
  Authors" (`pre-commit` adds it if missing). Code blocks below omit it.
- The editor keeps its bare imports (`store/…`, `common/…`, `features/…`). Code inside
  `packages/ui` imports its own files through `#…` (package.json `imports`) or from the
  same folder, never `../`.
- `packages/ui` is `"private": true`, version `0.0.0`, and never imports Redux,
  react-redux, axios, Auth0, wouter, or editor code.
- Type-check with `tsc -b`, never bare `tsc --noEmit`.
- `$SCRATCH` is a directory outside the repository for notes and PR bodies (the session
  scratchpad, or `mktemp -d`). Codemods use `perl -pi`, which behaves the same on macOS
  and Linux.
- Comments say what the code does and why, never what changed. American spelling.
- Commit messages end with
  `Co-Authored-By: <the model you are running as> <noreply@anthropic.com>`; PR bodies
  follow `.github/PULL_REQUEST_TEMPLATE.md` and end with
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Review Focus

1. **A stale `ui/` directory after pulling W1.** Developers keep an untracked
   `ui/node_modules` and `ui/.env`. Expected: the dev server and image builds read
   `frontend/apps/editor/.env`, and a missing Auth0 setting names that path. Pinned in
   Task 5 (error message and README) and Task 4 (image build).
2. **A reaction that has not loaded yet.** Every hook returns an empty value (`null`,
   `undefined`, `[]`, `{}`) rather than throwing. Pinned in Task 12.
3. **Templates' string IDs** (`template_<n>`). The Redux source and the provider treat
   them like dataset IDs. Pinned in Task 13.
4. **Previews arriving after the first render**, from the worker. `usePreviews`
   re-renders when they land. Pinned in Task 13.
5. **The image build from `frontend/`** on a clean checkout, including the Auth0 build
   arguments. Pinned in Task 4.

---

## PR W1: move the frontend into an npm workspace

Branch `frontend-workspace`. No source file changes; `git mv` keeps history.

### Task 1: Record the baseline

**Files:** none changed. Notes go in the scratchpad, not the repository.

- [ ] **Step 1: Branch and clean install**

```bash
cd ~/ord/ord-app && git switch main && git pull --ff-only && git switch -c frontend-workspace
rm -rf ui/node_modules && (cd ui && npm ci)
```

- [ ] **Step 2: Record what passes today**

```bash
cd ~/ord/ord-app/ui
npm run lint:check
npx tsc -b
npx vitest run 2>&1 | tail -5          # note the test file and test counts
npm run build
jq -r '.packages | to_entries[] | select(.key | startswith("node_modules/")) | "\(.key) \(.value.version)"' \
  package-lock.json | sort > "$SCRATCH/versions-before.txt"
```

Expected: all green. Keep the Vitest counts; W1 must reproduce them exactly.

### Task 2: Move `ui/` to `frontend/apps/editor` and create the workspace root

**Files:**

- Move: `ui/` → `frontend/apps/editor/` (everything, including `.npmrc` from #837,
  `.env.template`, `.gitignore`, `README.md`, `UI_Generated_Documentation.md`)
- Move: `frontend/apps/editor/package-lock.json` → `frontend/package-lock.json`
- Move: `frontend/apps/editor/.npmrc` → `frontend/.npmrc`
- Create: `frontend/package.json`
- Modify: `frontend/apps/editor/package.json`

- [ ] **Step 1: Move the tree**

```bash
cd ~/ord/ord-app
mkdir -p frontend/apps
git mv ui frontend/apps/editor
git mv frontend/apps/editor/package-lock.json frontend/package-lock.json
git mv frontend/apps/editor/.npmrc frontend/.npmrc
```

- [ ] **Step 2: Create `frontend/package.json`**

Move these `devDependencies` entries, with their exact version ranges, out of
`frontend/apps/editor/package.json` and into the root: `@eslint/js`, `eslint`,
`eslint-config-prettier`, `eslint-plugin-no-relative-import-paths`,
`eslint-plugin-prettier`, `eslint-plugin-react`, `eslint-plugin-react-hooks`,
`eslint-plugin-react-refresh`, `eslint-plugin-sonarjs`, `globals`, `jscpd`, `prettier`,
`stylelint`, `stylelint-config-standard`, `stylelint-scss`, `typescript`,
`typescript-eslint`. Move the whole `overrides` block too: npm honors `overrides` only
in the workspace root.

```json
{
  "name": "ord-app-frontend",
  "private": true,
  "type": "module",
  "workspaces": ["apps/*", "packages/*"],
  "scripts": {
    "build": "npm run build --workspaces --if-present",
    "lint": "eslint .",
    "lint:fix": "eslint --fix .",
    "lint:css": "stylelint '**/*.[s]css'",
    "lint:css:fix": "stylelint --fix '**/*.[s]css'",
    "lint:check": "prettier --check . && npm run lint && npm run lint:css",
    "prettier": "prettier --write .",
    "test:coverage": "npm run test:coverage --workspaces --if-present",
    "typecheck": "tsc -b"
  },
  "devDependencies": {
    "…": "the entries listed above, versions unchanged"
  },
  "overrides": {
    "…": "the editor's overrides block, unchanged"
  }
}
```

- [ ] **Step 3: Trim the editor's `package.json`**

Set `"name": "@open-reaction-database/editor"`. Delete the scripts that move to the
root: `prettier`, `lint`, `lint:fix`, `lint:css`, `lint:css:fix`, `lint:check`. Keep
`analyze`, `dev`, `build`, `preview`, `test`, `test:coverage`, `test:e2e`. Delete the
`overrides` block and the devDependencies moved in Step 2.

- [ ] **Step 4: Install and confirm no version moved**

```bash
cd ~/ord/ord-app/frontend && npm install
jq -r '.packages | to_entries[] | select(.key | startswith("node_modules/")) | "\(.key) \(.value.version)"' \
  package-lock.json | sort > "$SCRATCH/versions-after.txt"
diff "$SCRATCH/versions-before.txt" "$SCRATCH/versions-after.txt"
```

Expected: no differences, or only `node_modules/@open-reaction-database/editor` (the
workspace link) and packages that moved from `apps/editor/node_modules/…` to the root
with the same version. Any changed version is a bug in the move: restore the old range
and reinstall. Then `git status` must show no `node_modules`; if it does, add
`node_modules` to a new `frontend/.gitignore`.

### Task 3: Root tool configuration

**Files:**

- Move: `frontend/apps/editor/{eslint.config.mjs,.prettierrc.json,.prettierignore,.stylelintrc.json,.stylelintignore}` → `frontend/`
- Create: `frontend/tsconfig.json`
- Modify: `frontend/eslint.config.mjs`, `frontend/.stylelintignore`

- [ ] **Step 1: Move the configs**

```bash
cd ~/ord/ord-app/frontend
for f in eslint.config.mjs .prettierrc.json .prettierignore .stylelintrc.json .stylelintignore; do
  git mv "apps/editor/$f" "$f"
done
```

- [ ] **Step 2: Scope the ESLint config to the workspace**

In `frontend/eslint.config.mjs`:

- Change `{ ignores: ['dist'] }` to
  `{ ignores: ['**/dist', '**/coverage', '**/playwright-report', '**/test-results'] }`.
- Remove `no-relative-import-paths` from the main block's `plugins` and `rules`, and
  delete the `settings['import/resolver']` entry (no import plugin reads it).
- Append an editor-only block:

```js
  {
    files: ['apps/editor/**/*.{ts,tsx}'],
    plugins: { 'no-relative-import-paths': noRelativeImportPaths },
    rules: {
      'no-relative-import-paths/no-relative-import-paths': [
        'error',
        { allowSameFolder: true, rootDir: 'apps/editor/src', allowedDepth: 2 },
      ],
    },
  },
```

- [ ] **Step 3: Point `.stylelintignore` at the new paths**

```text
**/dist/**
apps/editor/src/common/styling/colors.module.scss
```

- [ ] **Step 4: Add the root TypeScript solution**

`frontend/tsconfig.json`:

```json
{
  "files": [],
  "references": [{ "path": "./apps/editor" }]
}
```

- [ ] **Step 5: Reproduce the baseline**

```bash
cd ~/ord/ord-app/frontend
npm run lint:check
npm run typecheck
(cd apps/editor && npx vitest run 2>&1 | tail -5)
npm run build
```

Expected: everything green, with the same Vitest counts as Task 1. ESLint now also
reaches `apps/editor/e2e/` and the config files; fix any finding there in place. If
`npm run typecheck` rejects the nested solution, reference
`./apps/editor/tsconfig.app.json` and `./apps/editor/tsconfig.node.json` directly.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add -A frontend ui
git commit -m "Move the frontend into an npm workspace at frontend/"
```

`git add -A` is safe here only because Steps 1–4 touched nothing outside `frontend/`
and the removed `ui/`; check `git status` first.

### Task 4: CI, hooks, duplication check, and the image

**Files:**

- Modify: `.github/workflows/ui_checks.yml`, `.github/workflows/tests.yml`,
  `.github/workflows/checks.yml`, `.pre-commit-config.yaml`, `.jscpd.json`, `Makefile`,
  `Dockerfile.single`, `.dockerignore`, `scripts/dev-e2e.sh`

- [ ] **Step 1: `ui_checks.yml`**

- Both `paths` filters: `'ui/**'` → `'frontend/**'`.
- `defaults.run.working-directory: ./ui` → `./frontend`.
- `lint_and_build_ui`: keep `npm ci` and `npm run lint:check`. In the Auth0 check, run
  Vite from the editor:
  `(cd apps/editor && ORD_APP_REQUIRE_AUTH0=true ../../node_modules/.bin/vite build) > "$RUNNER_TEMP/auth0.log" 2>&1 || true`.
  Keep `npm run build` with its env block. Add `- run: npm run typecheck` after
  `lint:check`.
- `test_ui`: keep `npm ci` and `npm run test:coverage`. The coverage summary reads
  `apps/editor/coverage/coverage-summary.json` (wrap the existing `jq` in
  `for project in apps/editor packages/ui; do … done`, skipping a project without the
  file, and title each table with the project). Upload path:
  `frontend/apps/editor/coverage/` (W2 adds `frontend/packages/ui/coverage/`).

- [ ] **Step 2: `tests.yml` (`test_e2e`)**

- Both `working-directory: ui` → `frontend`.
- `npm --prefix ui run dev -- …` → `npm --prefix frontend -w apps/editor run dev -- …`.
- `npm --prefix ui run test:e2e` → `npm --prefix frontend -w apps/editor run test:e2e`.
- Upload paths: `frontend/apps/editor/playwright-report/` and
  `frontend/apps/editor/test-results/`.

- [ ] **Step 3: `checks.yml` (`check_duplication`)**

`cache-dependency-path: frontend/package-lock.json`; `npm --prefix frontend ci`;
`frontend/node_modules/.bin/jscpd --config .jscpd.json`. Update the comment above the
job to say `frontend/`.

- [ ] **Step 4: `.jscpd.json`, `Makefile`, `.pre-commit-config.yaml`**

- `.jscpd.json` `path`: `["ord_app", "frontend/apps/editor/src"]`.
- `Makefile`: `frontend/node_modules/.bin/jscpd --config .jscpd.json`, and the comment
  says `npm ci` under `frontend/`.
- `.pre-commit-config.yaml`: `npm --prefix ui run …` → `npm --prefix frontend run …`;
  `files: ^ui/` → `^frontend/` in the prettier, eslint, and stylelint hooks; the jscpd
  hook's entry becomes `frontend/node_modules/.bin/jscpd --config .jscpd.json` and its
  `files` becomes `^(ord_app|frontend/(apps|packages)/[^/]+/src)/.*\.(py|ts|tsx)$`.
  Update the comments that say `ui/`.

- [ ] **Step 5: `Dockerfile.single` and `.dockerignore`**

```dockerfile
# Stage 1: Build the React app
FROM node:22-alpine AS react-build

WORKDIR /app

# Copy the frontend workspace
COPY frontend/ ./

# Install dependencies
RUN npm ci --ignore-scripts
```

Keep the `ARG`/`ENV` lines; in their comments, `ui/.env` becomes
`frontend/apps/editor/.env`. The build and copy become:

```dockerfile
RUN ORD_APP_REQUIRE_AUTH0=true npm run build -w apps/editor
```

```dockerfile
COPY --from=react-build /app/apps/editor/dist /var/www/html
```

`.dockerignore`: replace `ui/node_modules/` with `**/node_modules/`.

- [ ] **Step 6: `scripts/dev-e2e.sh`**

`( cd ui && …` → `( cd frontend/apps/editor && …`, and the usage comment
`cd ui && npm run test:e2e` → `cd frontend/apps/editor && npm run test:e2e`.

- [ ] **Step 7: Build the image from a clean tree** (Review Focus 5)

```bash
cd ~/ord/ord-app
git stash --include-untracked --keep-index   # only if git status shows strays
docker build -f Dockerfile.single \
  --build-arg VITE_AUTH0_DOMAIN=auth0.example.com --build-arg VITE_AUTH0_CLIENT_ID=placeholder \
  --build-arg VITE_AUTH0_AUDIENCE=https://auth0.example.com/api/v2/ \
  --build-arg VITE_AUTH0_ISSUER=https://auth0.example.com/ --build-arg VITE_AUTH0_SCOPE=openid \
  -t ord-app:frontend-workspace .
docker run --rm --entrypoint ls ord-app:frontend-workspace /var/www/html
docker build -f Dockerfile.single -t ord-app:no-auth0 . 2>&1 | grep 'Missing VITE_AUTH0_DOMAIN'
```

Expected: the first build succeeds and lists `index.html` and `assets`; the second
fails with the `Missing VITE_AUTH0_DOMAIN` message. Then `git stash pop` if you stashed.

- [ ] **Step 8: Run the end-to-end suite locally**

Start Postgres as `scripts/dev-e2e.sh` describes, run the script, and in another shell
`cd frontend/apps/editor && npm run test:e2e`. Expected: the smoke test passes.

- [ ] **Step 9: Commit**

```bash
git add .github/workflows/ui_checks.yml .github/workflows/tests.yml .github/workflows/checks.yml \
  .pre-commit-config.yaml .jscpd.json Makefile Dockerfile.single .dockerignore scripts/dev-e2e.sh
git commit -m "Point CI, hooks, and the image build at frontend/"
```

### Task 5: Documentation and messages that name `ui/`

**Files:**

- Modify: `CLAUDE.md`, `README.md`, `.claude/rules/ui-testing.md`,
  `.claude/skills/ord-app-ui-testing/SKILL.md`,
  `frontend/apps/editor/vite.config.ts`, `frontend/apps/editor/.env.template`,
  `frontend/apps/editor/UI_Generated_Documentation.md`

- [ ] **Step 1: The Auth0 error names the new path** (Review Focus 1)

In `frontend/apps/editor/vite.config.ts`, the thrown message becomes
`` `Missing ${missing.join(', ')}: pass them as build arguments or set them in frontend/apps/editor/.env (see frontend/apps/editor/.env.template).` ``
Prettier will wrap it. In `.env.template`, "Copy to ui/.env" becomes "Copy to
frontend/apps/editor/.env".

- [ ] **Step 2: Docs**

- `CLAUDE.md`: the layout bullet describes `frontend/` (workspace root:
  `apps/editor`, later `apps/viewer` and `packages/ui`); the "Frontend" section's
  commands run from `frontend/` (`npm ci`, `npm run lint:check`, `npm run typecheck`,
  `npm run test:coverage`) or with `-w apps/editor` (`dev`, `build`, `test:e2e`); the
  Conventions bullets say `frontend/apps/editor/.env` and
  `frontend/apps/editor/vite.config.ts`.
- `README.md`: `cd ui` → `cd frontend`, and the `.env` paths as above. Add one
  sentence: after pulling this change, delete any old `ui/` directory left behind
  (`ui/node_modules`, `ui/.env`) and copy `.env` to `frontend/apps/editor/.env`.
- `.claude/rules/ui-testing.md`: `paths: "ui/**/*"` → `"frontend/**/*"`; prose
  `ui/` → `frontend/`.
- `.claude/skills/ord-app-ui-testing/SKILL.md`: `cd ui` → `cd frontend/apps/editor`;
  the absolute Playwright path example uses `frontend/node_modules/@playwright/test`.
- `UI_Generated_Documentation.md`: replace `ui/` path prefixes with
  `frontend/apps/editor/`.

- [ ] **Step 3: Verify nothing still names the old path**

```bash
cd ~/ord/ord-app
git grep -n -E '(^|[^a-z_/])ui/' -- ':!*package-lock.json' ':!frontend/apps/editor/src' ':!frontend/apps/editor/e2e'
```

Expected: no hits that refer to the old directory.

- [ ] **Step 4: Commit and open the PR**

```bash
git add CLAUDE.md README.md .claude/rules/ui-testing.md .claude/skills/ord-app-ui-testing/SKILL.md \
  frontend/apps/editor/vite.config.ts frontend/apps/editor/.env.template \
  frontend/apps/editor/UI_Generated_Documentation.md
git commit -m "Name frontend/ in the docs and the Auth0 build error"
git push -u origin frontend-workspace
gh pr create --title "Move the frontend into an npm workspace" --body-file "$SCRATCH/w1-body.md"
```

The body says this is a move with no source changes, lists the CI, hook, and image
changes, and links the design. After CI is green, check that `lint_and_build_ui`,
`test_ui`, `test_e2e`, and `check_duplication` all ran (the path filters changed).

---

## PR W2: the shared package with the theme and display primitives

Branch `ui-package-theme`, from `main` after W1 merges.

### Task 6: Package skeleton and shared TypeScript options

**Files:**

- Create: `frontend/tsconfig.base.json`, `frontend/packages/ui/package.json`,
  `frontend/packages/ui/tsconfig.json`, `frontend/packages/ui/vitest.config.ts`,
  `frontend/packages/ui/README.md`, `frontend/packages/ui/src/testing/setup.ts`,
  `frontend/packages/ui/src/theme/theme.test.ts`
- Modify: `frontend/tsconfig.json`, `frontend/apps/editor/tsconfig.app.json`,
  `frontend/apps/editor/tsconfig.node.json`

**Interfaces:**

- Produces: package `@open-reaction-database/ui` with export `./theme` (Task 7),
  `./theme/global.scss` (Task 7), `./display` (Task 8); internal imports `#<path>`
  mapping to `src/<path>`.

- [ ] **Step 1: `frontend/tsconfig.base.json`**

The options the editor's two configs share today, so every project extends one copy:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true
  }
}
```

In `apps/editor/tsconfig.app.json` and `tsconfig.node.json`, add
`"extends": "../../tsconfig.base.json"` and delete the options now inherited, keeping
`tsBuildInfoFile`, `lib`, `types`, `useDefineForClassFields`, `jsx`, `paths`, and
`include`.

- [ ] **Step 2: `frontend/packages/ui/package.json`**

Copy each devDependency's range from `apps/editor/package.json`.

```json
{
  "name": "@open-reaction-database/ui",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "description": "Theme and components shared by the Open Reaction Database web apps.",
  "license": "Apache-2.0",
  "sideEffects": ["**/*.css", "**/*.scss"],
  "exports": {
    "./theme": "./src/theme/index.ts",
    "./theme/global.scss": "./src/theme/global.scss",
    "./display": "./src/display/index.ts"
  },
  "imports": {
    "#*": "./src/*"
  },
  "scripts": {
    "test": "vitest",
    "test:coverage": "vitest run --coverage"
  },
  "peerDependencies": {
    "@mantine/core": "<editor's range>",
    "react": "<editor's range>",
    "react-dom": "<editor's range>"
  },
  "dependencies": {
    "clsx": "<editor's range>"
  },
  "devDependencies": {
    "@mantine/core": "<editor's range>",
    "@testing-library/jest-dom": "<editor's range>",
    "@testing-library/react": "<editor's range>",
    "@vitejs/plugin-react-swc": "<editor's range>",
    "@vitest/coverage-v8": "<editor's range>",
    "happy-dom": "<editor's range>",
    "react": "<editor's range>",
    "react-dom": "<editor's range>",
    "sass": "<editor's range>",
    "vite": "<editor's range>",
    "vitest": "<editor's range>"
  }
}
```

Add `"@open-reaction-database/ui": "0.0.0"` to the editor's `dependencies`.

- [ ] **Step 3: `packages/ui/tsconfig.json`, `vitest.config.ts`, test setup**

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.tsbuildinfo",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "jsx": "react-jsx",
    "types": ["vitest/globals", "vite/client"]
  },
  "include": ["src", "vitest.config.ts"]
}
```

```ts
import react from '@vitejs/plugin-react-swc';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: ['./src/testing/setup.ts'],
    mockReset: true,
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'html', 'lcov', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/**/*.d.ts', 'src/testing/**'],
    },
  },
});
```

`src/testing/setup.ts`:

```ts
// Registers jest-dom matchers (toBeInTheDocument, etc.).
import '@testing-library/jest-dom/vitest';
```

Add `{ "path": "./packages/ui" }` to `frontend/tsconfig.json`'s references. Write
`packages/ui/README.md`: one paragraph on what the package holds, that apps import it
only through its `exports`, and that it is consumed as source and not published.

- [ ] **Step 4: Write the failing test**

`packages/ui/src/theme/theme.test.ts`:

```ts
import { theme } from '#theme/index.ts';

describe('theme', () => {
  it('uses the ORD blue as its primary color', () => {
    expect(theme.primaryColor).toBe('primary');
    expect(theme.colors?.primary?.[0]).toBe('#3C78D8');
  });
});
```

- [ ] **Step 5: Run it and watch it fail**

Run: `cd ~/ord/ord-app/frontend && npm install && npx vitest run --root packages/ui`
Expected: FAIL, because `#theme/index.ts` does not resolve yet.

### Task 7: Move the theme into the package

**Files:**

- Move: `apps/editor/src/common/styling/*` → `packages/ui/src/theme/`
- Create: `packages/ui/src/theme/global.scss`
- Modify: `packages/ui/src/theme/index.ts`, `apps/editor/src/index.scss`,
  `apps/editor/src/main.tsx`, every editor file importing `common/styling`,
  `frontend/.stylelintignore`

**Interfaces:**

- Produces: `@open-reaction-database/ui/theme` exporting `theme`,
  `colorToCssVariable`, `typographyClasses`, `buttonClasses`;
  `@open-reaction-database/ui/theme/global.scss`, the `:root` variables and global
  element rules.

- [ ] **Step 1: Move the files**

```bash
cd ~/ord/ord-app/frontend
mkdir -p packages/ui/src/theme
git mv apps/editor/src/common/styling/* packages/ui/src/theme/
```

- [ ] **Step 2: The barrel**

`packages/ui/src/theme/index.ts`:

```ts
export * from './theme.ts';
export { colorToCssVariable } from './colors.ts';
export { default as typographyClasses } from './typography.module.scss';
export { default as buttonClasses } from './buttons.module.scss';
```

- [ ] **Step 3: Split the global stylesheet**

Move everything in `apps/editor/src/index.scss` after the four library `@import`
lines — the `:root` block and the `button.mantine-Button-root`,
`button[data-variant='transparent']`, and `a` rules — into
`packages/ui/src/theme/global.scss`, unchanged. The editor's `index.scss` keeps the
four `@import` lines. In `apps/editor/src/main.tsx`, add after `import './index.scss';`:

```ts
import '@open-reaction-database/ui/theme/global.scss';
```

- [ ] **Step 4: Rewrite the editor's imports**

| Today | Becomes |
| --- | --- |
| `from 'common/styling'` (19 files) | `from '@open-reaction-database/ui/theme'` |
| `from '../../styling'` (2 files) | `from '@open-reaction-database/ui/theme'` |
| `from 'common/styling/colors.ts'` (5 files) | `from '@open-reaction-database/ui/theme'` |
| `from 'common/styling/theme.ts'` (`core/AppRoot.tsx`) | `from '@open-reaction-database/ui/theme'` |

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
git grep -l -E "from '(common/styling[^']*|(\.\./)+styling)'" -- . |
  xargs perl -pi -e "s#from '(common/styling[^']*|(\.\./)+styling)'#from '\@open-reaction-database/ui/theme'#g"
git grep -n "styling'" -- .     # expect no hits
```

In `frontend/.stylelintignore`, the colors line becomes
`packages/ui/src/theme/colors.module.scss`.

- [ ] **Step 5: Run the theme test and the editor's suite**

```bash
cd ~/ord/ord-app/frontend
npx vitest run --root packages/ui
(cd apps/editor && npx vitest run 2>&1 | tail -5)
npm run typecheck && npm run build
```

Expected: the theme test PASSES; the editor's counts match W1's. This step is also
the check that `#…` imports resolve in Vite, Vitest, and `tsc -b`. If any of them
rejects `#theme/index.ts`, switch the package to same-folder and relative imports, delete
the `imports` field, and record the switch in the PR body.

- [ ] **Step 6: Look at it**

`npm -w apps/editor run dev`, sign in through the no-auth mode
(`VITE_E2E_NO_AUTH=TRUE`, as in `scripts/dev-e2e.sh`), and compare the datasets list
and a reaction page with `main`: the same blue, gray background, Roboto, and orange
link hover.

- [ ] **Step 7: Commit**

```bash
cd ~/ord/ord-app
git add frontend
git commit -m "Move the theme into @open-reaction-database/ui"
```

### Task 8: Move the display primitives into the package

**Files:**

- Move: `apps/editor/src/common/components/display/{KeyValueDisplay,RequiredOptionalFields,DataField,Counter}/` → `packages/ui/src/display/`
- Create: `packages/ui/src/display/index.ts`
- Modify: every editor file importing them (25 imports)

**Interfaces:**

- Produces: `@open-reaction-database/ui/display` exporting `KeyValueDisplay`,
  `RequiredOptionalFields`, `RequiredOptionalFieldsProps`, `DataField`, `Counter`.

- [ ] **Step 1: Move them with their tests and styles**

```bash
cd ~/ord/ord-app/frontend
mkdir -p packages/ui/src/display
for c in KeyValueDisplay RequiredOptionalFields DataField Counter; do
  git mv "apps/editor/src/common/components/display/$c" "packages/ui/src/display/$c"
done
```

- [ ] **Step 2: Fix their internal imports**

- `KeyValueDisplay.tsx`: `from 'common/styling'` → `from '#theme/index.ts'`.
- `RequiredOptionalFields.tsx`: `from '../KeyValueDisplay/KeyValueDisplay.tsx'` →
  `from '#display/KeyValueDisplay/KeyValueDisplay.tsx'`.
- Their tests render with `MantineProvider`. Add
  `packages/ui/src/testing/renderWithMantine.tsx` (copy the editor's
  `src/test/renderWithMantine.tsx`) and point the moved tests' imports at
  `#testing/renderWithMantine.tsx`.

- [ ] **Step 3: The barrel**

`packages/ui/src/display/index.ts`:

```ts
export { Counter } from './Counter/Counter.tsx';
export { DataField } from './DataField/DataField.tsx';
export { KeyValueDisplay } from './KeyValueDisplay/KeyValueDisplay.tsx';
export { RequiredOptionalFields } from './RequiredOptionalFields/RequiredOptionalFields.tsx';
export type { RequiredOptionalFieldsProps } from './RequiredOptionalFields/requiredOptionalFields.types.ts';
```

Check each component's actual export names before writing this; if a module exports
more than the component (such as a props type used elsewhere), export that too.

- [ ] **Step 4: Rewrite the editor's imports**

Every `from 'common/components/display/(KeyValueDisplay|RequiredOptionalFields|DataField|Counter)/…'`
becomes `from '@open-reaction-database/ui/display'`, merging into one import statement
per file where a file imports several (the `no-duplicate-imports` rule enforces it).

```bash
cd ~/ord/ord-app/frontend/apps/editor/src
git grep -l -E "components/display/(KeyValueDisplay|RequiredOptionalFields|DataField|Counter)/" -- . |
  xargs perl -pi -e "s#from '[^']*components/display/(KeyValueDisplay|RequiredOptionalFields|DataField|Counter)/[^']*'#from '\@open-reaction-database/ui/display'#g"
cd ../../.. && npm run lint:fix
```

Then resolve any `no-duplicate-imports` errors by hand.

- [ ] **Step 5: Verify**

```bash
cd ~/ord/ord-app/frontend
npx vitest run --root packages/ui     # the moved tests pass here
(cd apps/editor && npx vitest run 2>&1 | tail -5)   # counts drop by exactly the moved test files
npm run lint:check && npm run typecheck && npm run build
```

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app && git add frontend
git commit -m "Move the display primitives into @open-reaction-database/ui"
```

### Task 9: Enforce the package boundary

**Files:**

- Modify: `frontend/package.json` (devDependencies), `frontend/eslint.config.mjs`

- [ ] **Step 1: Install the lint plugins**

```bash
cd ~/ord/ord-app/frontend
npm install -D eslint-plugin-import-x eslint-import-resolver-typescript
```

- [ ] **Step 2: Add the package block**

```js
import { createTypeScriptImportResolver } from 'eslint-import-resolver-typescript';
import importX from 'eslint-plugin-import-x';
```

```js
  {
    files: ['packages/ui/**/*.{ts,tsx}'],
    plugins: { 'import-x': importX },
    settings: {
      'import-x/resolver-next': [
        createTypeScriptImportResolver({ project: 'packages/ui/tsconfig.json' }),
      ],
    },
    rules: {
      // Every import must be declared in the package's own package.json; hoisting would
      // otherwise let an undeclared dependency resolve from the workspace root.
      'import-x/no-extraneous-dependencies': [
        'error',
        {
          packageDir: [path.join(import.meta.dirname, 'packages/ui')],
          devDependencies: ['**/*.test.{ts,tsx}', '**/testing/**', '**/vitest.config.ts'],
        },
      ],
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            { group: ['../*'], message: 'Import package files through #… instead.' },
            {
              group: ['react-redux', '@reduxjs/toolkit', 'axios', '@auth0/*', 'wouter'],
              message: 'The shared package stays free of app state, transport, and routing.',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['apps/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@open-reaction-database/ui/src/*', '**/packages/ui/*'],
              message: 'Import the shared package only through its exports.',
            },
          ],
        },
      ],
    },
  },
```

Add `import path from 'node:path';` at the top.

- [ ] **Step 3: Prove each rule fires**

Add, one at a time, to `packages/ui/src/display/Counter/Counter.tsx`:
`import { Provider } from 'react-redux';`, then `import dayjs from 'dayjs';` (a
dependency of the editor only), then `import x from '../DataField/DataField.tsx';`; and
to any editor file `import { theme } from '@open-reaction-database/ui/src/theme/index.ts';`.
Run `npm run lint` after each. Expected: one error per planted import, naming the rule.
Remove each plant.

- [ ] **Step 4: Commit**

```bash
cd ~/ord/ord-app && git add frontend/package.json frontend/package-lock.json frontend/eslint.config.mjs
git commit -m "Lint the shared package's dependencies and the apps' imports of it"
```

### Task 10: CI coverage and duplication for the package

**Files:**

- Modify: `frontend/packages/ui/vitest.config.ts`, `.github/workflows/ui_checks.yml`,
  `.jscpd.json`

- [ ] **Step 1: Set the package's coverage floor**

Run `cd ~/ord/ord-app/frontend && npm -w packages/ui run test:coverage` and read the
totals. Add `thresholds` to the package's coverage block at each metric's measured
value rounded down to a whole percent, with a comment that they are a floor to raise.

- [ ] **Step 2: CI**

In `test_ui`, add `frontend/packages/ui/coverage/` to the upload `path` list (the
summary loop from Task 4 already covers it). In `.jscpd.json`, `path` becomes
`["ord_app", "frontend/apps/editor/src", "frontend/packages/ui/src"]`.

- [ ] **Step 3: Full check, commit, PR**

```bash
cd ~/ord/ord-app/frontend
npm run lint:check && npm run typecheck && npm run test:coverage && npm run build
cd .. && frontend/node_modules/.bin/jscpd --config .jscpd.json
git add frontend/packages/ui/vitest.config.ts .github/workflows/ui_checks.yml .jscpd.json
git commit -m "Measure the shared package's coverage and duplication in CI"
git push -u origin ui-package-theme
gh pr create --title "Start the shared UI package with the theme and display primitives" \
  --body-file "$SCRATCH/w2-body.md"
```

---

## PR A: the reaction provider

Branch `reaction-provider`, from `main` after W2 merges. All new provider files live in
`frontend/apps/editor/src/features/reactions/provider/` until step G moves them into the
package; they already follow the package's rules (no Redux or transport imports), and
Task 14 makes the linter hold them to it.

### Task 11: Provider types, input ordering, and the static source

**Files:**

- Create: `provider/reactionProvider.types.ts`, `provider/orderInputs.ts`,
  `provider/orderInputs.test.ts`, `provider/staticReactionSource.ts`,
  `provider/staticReactionSource.test.ts`
- Modify: `apps/editor/src/store/entities/reactions/reactions.selectors.ts`

(`provider/` is `frontend/apps/editor/src/features/reactions/provider/`.)

**Interfaces:**

- Produces:
  - `type ReactionSnapshot = BaseReaction & Partial<Pick<DatasetReaction, 'pb_reaction_id' | 'is_valid' | 'validation'>>`
  - `interface ReactionSource { getSnapshot(): ReactionSnapshot | undefined; getPreviews(): PreviewStatesById; subscribe(listener: () => void): () => void }`
  - `interface ReactionActions { update(pathComponents: ReactionPathComponents, newValue: unknown): Promise<void>; remove(pathComponents: ReactionPathComponents): Promise<void> }`
  - `interface ReactionSlots { ViewDeleteButtons: FC<ReactionViewDeleteButtonsProps>; ValueLabel: FC<ReactionValueLabelProps>; ViewOnlyLabel: FC<ReactionValueLabelProps> }`
  - `interface ReactionProviderValue { source: ReactionSource; actions?: ReactionActions; isTemplate: boolean; slots: ReactionSlots }`
  - `function orderInputs(inputs: Record<string, ReactionInput>): Array<ReactionInput>`
  - `function createStaticReactionSource(snapshot: ReactionSnapshot | undefined, previews?: PreviewStatesById): ReactionSource`

- [ ] **Step 1: Types**

`provider/reactionProvider.types.ts`:

```ts
import type { FC } from 'react';
import type { ReactionPathComponents } from 'common/types/reaction/reactionPathComponents.ts';
import type { ReactionValueLabelProps } from 'features/reactions/ReactionInteractions/ReactionValueLabel/reactionValueLabel.types.ts';
import type { ReactionViewDeleteButtonsProps } from 'features/reactions/ReactionInteractions/ReactionViewDeleteButtons/reactionViewDeleteButtons.types.ts';
import type {
  BaseReaction,
  DatasetReaction,
} from 'store/entities/reactions/reactions.types.ts';
import type { PreviewStatesById } from 'store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts';

/**
 * One reaction as its source holds it. A dataset reaction carries its ORD ID, validity, and
 * validation; a template carries none of them.
 */
export type ReactionSnapshot = BaseReaction &
  Partial<Pick<DatasetReaction, 'pb_reaction_id' | 'is_valid' | 'validation'>>;

/** One reaction's data and molecule previews, read through `useSyncExternalStore`. */
export interface ReactionSource {
  /** Returns the same object until the reaction changes, or undefined before it loads. */
  getSnapshot(): ReactionSnapshot | undefined;
  /** Returns the same object until a preview changes. */
  getPreviews(): PreviewStatesById;
  subscribe(listener: () => void): () => void;
}

/** Edits to one reaction. A provider given no actions is read-only. */
export interface ReactionActions {
  update(pathComponents: ReactionPathComponents, newValue: unknown): Promise<void>;
  remove(pathComponents: ReactionPathComponents): Promise<void>;
}

/** Components the host app supplies for the parts of the view it owns. */
export interface ReactionSlots {
  ViewDeleteButtons: FC<ReactionViewDeleteButtonsProps>;
  ValueLabel: FC<ReactionValueLabelProps>;
  ViewOnlyLabel: FC<ReactionValueLabelProps>;
}

export interface ReactionProviderValue {
  source: ReactionSource;
  actions?: ReactionActions;
  isTemplate: boolean;
  slots: ReactionSlots;
}
```

- [ ] **Step 2: Failing tests for `orderInputs`**

`provider/orderInputs.test.ts`:

```ts
import type { ReactionInput } from 'store/entities/reactions/reactionsInputs/reactionInputs.types.ts';
import { orderInputs } from './orderInputs.ts';

const input = (name: string, additionOrder?: number) =>
  ({ name, additionOrder }) as unknown as ReactionInput;

describe('orderInputs', () => {
  it('sorts by addition order, then by name', () => {
    const ordered = orderInputs({
      c: input('c', 2),
      b: input('b', 1),
      a: input('a', 2),
    });
    expect(ordered.map(item => item.name)).toEqual(['b', 'a', 'c']);
  });

  it('puts inputs without an addition order last, by name', () => {
    const ordered = orderInputs({ z: input('z'), y: input('y'), x: input('x', 5) });
    expect(ordered.map(item => item.name)).toEqual(['x', 'y', 'z']);
  });

  it('returns an empty list for no inputs', () => {
    expect(orderInputs({})).toEqual([]);
  });
});
```

Run: `cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/provider`
Expected: FAIL, `orderInputs.ts` does not exist.

- [ ] **Step 3: Implement it, and have the selector use it**

`provider/orderInputs.ts`:

```ts
import type { ReactionInput } from 'store/entities/reactions/reactionsInputs/reactionInputs.types.ts';

/** Sorts inputs by addition order, then by name; inputs without an order go last. */
export function orderInputs(inputs: Record<string, ReactionInput>): Array<ReactionInput> {
  return Object.values(inputs).sort((a, b) => {
    const aOrder = a.additionOrder ?? Infinity;
    const bOrder = b.additionOrder ?? Infinity;
    return aOrder === bOrder ? a.name.localeCompare(b.name) : aOrder - bOrder;
  });
}
```

In `reactions.selectors.ts`, `selectOrderedInputs`'s result function becomes
`(reactions, id) => orderInputs(reactions[id]?.data?.inputs || {})`, importing
`orderInputs` from `features/reactions/provider/orderInputs.ts`.

Run the provider tests and `src/store/entities/reactions/reactions.selectors.test.ts`.
Expected: PASS.

- [ ] **Step 4: Failing tests for the static source**

`provider/staticReactionSource.test.ts`:

```ts
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import type { ReactionSnapshot } from './reactionProvider.types.ts';
import { createStaticReactionSource } from './staticReactionSource.ts';

const snapshot = {
  data: emptyReactionData(),
  previews: {},
  summary: { provenance: {}, summary: {}, conditions: '' },
  pb_reaction_id: 'ord-0123',
} as ReactionSnapshot;

describe('createStaticReactionSource', () => {
  it('returns the same snapshot and previews on every call', () => {
    const previews = { a: { isLoading: false, svg: 'PHN2Zz4=' } };
    const source = createStaticReactionSource(snapshot, previews);
    expect(source.getSnapshot()).toBe(snapshot);
    expect(source.getSnapshot()).toBe(source.getSnapshot());
    expect(source.getPreviews()).toBe(previews);
  });

  it('defaults to no previews', () => {
    const source = createStaticReactionSource(snapshot);
    expect(source.getPreviews()).toBe(source.getPreviews());
    expect(source.getPreviews()).toEqual({});
  });

  it('can stand for a reaction that has not loaded', () => {
    expect(createStaticReactionSource(undefined).getSnapshot()).toBeUndefined();
  });

  it('never notifies, and unsubscribes cleanly', () => {
    const listener = vi.fn();
    const unsubscribe = createStaticReactionSource(snapshot).subscribe(listener);
    unsubscribe();
    expect(listener).not.toHaveBeenCalled();
  });
});
```

Run it. Expected: FAIL, module missing.

- [ ] **Step 5: Implement the static source**

`provider/staticReactionSource.ts`:

```ts
import type { PreviewStatesById } from 'store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts';
import type { ReactionSnapshot, ReactionSource } from './reactionProvider.types.ts';

const NO_PREVIEWS: PreviewStatesById = {};

function unsubscribe(): void {
  // A static source never changes, so there is nothing to stop listening to.
}

/** Creates a source over a reaction that never changes, such as one shown read-only. */
export function createStaticReactionSource(
  snapshot: ReactionSnapshot | undefined,
  previews: PreviewStatesById = NO_PREVIEWS,
): ReactionSource {
  return {
    getSnapshot: () => snapshot,
    getPreviews: () => previews,
    subscribe: () => unsubscribe,
  };
}
```

Run. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider frontend/apps/editor/src/store/entities/reactions/reactions.selectors.ts
git commit -m "Add the reaction source types, input ordering, and a static source"
```

### Task 12: `ReactionProvider` and its hooks, tested against the static source

**Files:**

- Create: `provider/reactionProvider.context.ts`, `provider/ReactionProvider.tsx`,
  `provider/reactionProvider.hooks.ts`, `provider/equality.ts`,
  `provider/reactionProvider.hooks.test.tsx`, `provider/renderWithReaction.tsx`
- Modify: `frontend/apps/editor/package.json` (add `use-sync-external-store` and
  `@types/use-sync-external-store`, at the versions react-redux already pulls in)

**Interfaces:**

- Consumes: Task 11's types, `orderInputs`, `createStaticReactionSource`.
- Produces:
  - `function ReactionProvider(props: { reactionId: ReactionId; source: ReactionSource; actions?: ReactionActions; isTemplate?: boolean; slots: ReactionSlots; children: ReactNode }): JSX.Element`
  - `useReactionSnapshot(): ReactionSnapshot | undefined`
  - `useReactionPart<T = unknown>(pathComponents: ReactionPathComponents): T | null`
  - `useOrderedInputs(): Array<ReactionInput>`
  - `usePreviews(entityIds: Array<string>): PreviewStatesById`
  - `useReactionActions(): ReactionActions | undefined`
  - `useIsViewOnly(): boolean`
  - `useReactionSlots(): ReactionSlots`
  - `renderWithReaction(ui: ReactElement, options: { reactionId?: ReactionId; snapshot?: ReactionSnapshot; source?: ReactionSource; actions?: ReactionActions; isTemplate?: boolean; slots?: Partial<ReactionSlots> }): RenderResult`

- [ ] **Step 1: Add the dependency**

```bash
cd ~/ord/ord-app/frontend
npm ls use-sync-external-store        # the version react-redux resolves
npm install -w apps/editor use-sync-external-store@<that version> @types/use-sync-external-store
```

- [ ] **Step 2: The test helper**

`provider/renderWithReaction.tsx`:

```tsx
// Test-only render helper, not an HMR boundary.
/* eslint-disable react-refresh/only-export-components */
import { MantineProvider } from '@mantine/core';
import { render, type RenderOptions } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import type { ReactionId } from 'store/entities/reactions/reactions.types.ts';
import { ReactionProvider } from './ReactionProvider.tsx';
import type {
  ReactionActions,
  ReactionSlots,
  ReactionSnapshot,
  ReactionSource,
} from './reactionProvider.types.ts';
import { createStaticReactionSource } from './staticReactionSource.ts';

const Empty = () => null;

const EMPTY_SLOTS: ReactionSlots = {
  ViewDeleteButtons: Empty,
  ValueLabel: Empty,
  ViewOnlyLabel: Empty,
};

interface RenderWithReactionOptions extends Omit<RenderOptions, 'wrapper'> {
  reactionId?: ReactionId;
  snapshot?: ReactionSnapshot;
  source?: ReactionSource;
  actions?: ReactionActions;
  isTemplate?: boolean;
  slots?: Partial<ReactionSlots>;
}

/** Renders under a ReactionProvider: a static source over `snapshot` unless a source is given. */
export function renderWithReaction(
  ui: ReactElement,
  {
    reactionId = 1,
    snapshot,
    source = createStaticReactionSource(snapshot),
    actions,
    isTemplate = false,
    slots,
    ...options
  }: RenderWithReactionOptions = {},
) {
  const allSlots = { ...EMPTY_SLOTS, ...slots };
  function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return (
      <MantineProvider>
        <ReactionProvider
          reactionId={reactionId}
          source={source}
          actions={actions}
          isTemplate={isTemplate}
          slots={allSlots}
        >
          {children}
        </ReactionProvider>
      </MantineProvider>
    );
  }
  return render(ui, { wrapper: Wrapper, ...options });
}
```

Step G moves this file to the package's `src/testing/`.

- [ ] **Step 3: Failing hook tests**

`provider/reactionProvider.hooks.test.tsx`:

```tsx
import { renderHook } from '@testing-library/react';
import { useContext, type ReactNode } from 'react';
import { reactionContext } from 'features/reactions/reactions.context.ts';
import type { ReactionInput } from 'store/entities/reactions/reactionsInputs/reactionInputs.types.ts';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import { ReactionProvider } from './ReactionProvider.tsx';
import {
  useIsViewOnly,
  useOrderedInputs,
  usePreviews,
  useReactionActions,
  useReactionPart,
  useReactionSnapshot,
} from './reactionProvider.hooks.ts';
import type {
  ReactionActions,
  ReactionSlots,
  ReactionSnapshot,
  ReactionSource,
} from './reactionProvider.types.ts';
import { createStaticReactionSource } from './staticReactionSource.ts';

const Empty = () => null;
const slots: ReactionSlots = { ViewDeleteButtons: Empty, ValueLabel: Empty, ViewOnlyLabel: Empty };

const input = (name: string, additionOrder: number) =>
  ({ name, additionOrder }) as unknown as ReactionInput;

const snapshot = {
  data: {
    ...emptyReactionData(),
    inputs: { second: input('second', 2), first: input('first', 1) },
  },
  previews: {},
  summary: { provenance: {}, summary: {}, conditions: '' },
} as ReactionSnapshot;

function wrapperFor(source: ReactionSource, actions?: ReactionActions) {
  return function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
    return (
      <ReactionProvider reactionId={7} source={source} actions={actions} slots={slots}>
        {children}
      </ReactionProvider>
    );
  };
}

describe('reaction hooks over a static source', () => {
  const source = createStaticReactionSource(snapshot, {
    a: { isLoading: false, svg: 'A' },
    b: { isLoading: true, svg: null },
  });
  const wrapper = wrapperFor(source);

  it('return the snapshot and parts of it by path', () => {
    expect(renderHook(useReactionSnapshot, { wrapper }).result.current).toBe(snapshot);
    const { result } = renderHook(() => useReactionPart(['inputs', 'first']), { wrapper });
    expect(result.current).toBe(snapshot.data.inputs.first);
  });

  it('return null for a path that does not exist', () => {
    const { result } = renderHook(() => useReactionPart(['inputs', 'missing', 'name']), {
      wrapper,
    });
    expect(result.current).toBeNull();
  });

  it('order inputs', () => {
    const { result } = renderHook(useOrderedInputs, { wrapper });
    expect(result.current.map(item => item.name)).toEqual(['first', 'second']);
  });

  it('pick previews by ID, keeping unknown IDs as undefined', () => {
    const { result } = renderHook(() => usePreviews(['a', 'zzz']), { wrapper });
    expect(result.current).toEqual({ a: { isLoading: false, svg: 'A' }, zzz: undefined });
  });

  it('are read-only without actions, and supply the old context as view-only', () => {
    expect(renderHook(useIsViewOnly, { wrapper }).result.current).toBe(true);
    expect(renderHook(useReactionActions, { wrapper }).result.current).toBeUndefined();
    const legacy = renderHook(() => useContext(reactionContext), { wrapper }).result.current;
    expect(legacy).toMatchObject({ reactionId: 7, isTemplate: false, isViewOnly: true });
    expect(legacy.ViewDeleteButtonsComponent).toBe(Empty);
  });

  it('are editable with actions', () => {
    const actions: ReactionActions = { update: vi.fn(), remove: vi.fn() };
    const editable = wrapperFor(source, actions);
    expect(renderHook(useIsViewOnly, { wrapper: editable }).result.current).toBe(false);
    expect(renderHook(useReactionActions, { wrapper: editable }).result.current).toBe(actions);
    const legacy = renderHook(() => useContext(reactionContext), { wrapper: editable });
    expect(legacy.result.current.isViewOnly).toBe(false);
  });
});

describe('reaction hooks before the reaction loads', () => {
  const wrapper = wrapperFor(createStaticReactionSource(undefined));

  it('return empty values instead of throwing', () => {
    expect(renderHook(useReactionSnapshot, { wrapper }).result.current).toBeUndefined();
    expect(renderHook(() => useReactionPart(['notes']), { wrapper }).result.current).toBeNull();
    expect(renderHook(useOrderedInputs, { wrapper }).result.current).toEqual([]);
    expect(renderHook(() => usePreviews([]), { wrapper }).result.current).toEqual({});
  });
});

describe('reaction hooks outside a provider', () => {
  it('throw a message naming the provider', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    expect(() => renderHook(useReactionSnapshot)).toThrow(/ReactionProvider/);
  });
});
```

Run it. Expected: FAIL, modules missing.

- [ ] **Step 4: Equality helpers**

`provider/equality.ts`:

```ts
/** Whether two arrays hold the same items, by identity, in the same order. */
export function shallowEqualArrays<T>(a: ReadonlyArray<T>, b: ReadonlyArray<T>): boolean {
  return a.length === b.length && a.every((item, index) => Object.is(item, b[index]));
}

/** Whether two records have the same keys, each holding the same value by identity. */
export function shallowEqualRecords<T>(
  a: Readonly<Record<string, T>>,
  b: Readonly<Record<string, T>>,
): boolean {
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every(key => Object.hasOwn(b, key) && Object.is(a[key], b[key]))
  );
}
```

- [ ] **Step 5: Context, provider, and hooks**

`provider/reactionProvider.context.ts`:

```ts
import { createContext } from 'react';
import type { ReactionProviderValue } from './reactionProvider.types.ts';

export const reactionProviderContext = createContext<ReactionProviderValue | null>(null);
```

`provider/ReactionProvider.tsx`:

```tsx
import { useMemo, type ReactNode } from 'react';
import { reactionContext } from 'features/reactions/reactions.context.ts';
import type { ReactionsContext } from 'features/reactions/reactions.types.ts';
import type { ReactionId } from 'store/entities/reactions/reactions.types.ts';
import { reactionProviderContext } from './reactionProvider.context.ts';
import type {
  ReactionActions,
  ReactionProviderValue,
  ReactionSlots,
  ReactionSource,
} from './reactionProvider.types.ts';

interface ReactionProviderProps {
  /** The ID that components still reading `reactionContext` select by. */
  reactionId: ReactionId;
  source: ReactionSource;
  actions?: ReactionActions;
  isTemplate?: boolean;
  slots: ReactionSlots;
  children: ReactNode;
}

/**
 * Supplies one reaction, its edit actions if it can be edited, and the host app's slot
 * components to the view beneath. It also supplies `reactionContext` for the components
 * that have not moved to the hooks.
 */
export function ReactionProvider({
  reactionId,
  source,
  actions,
  isTemplate = false,
  slots,
  children,
}: Readonly<ReactionProviderProps>) {
  const value = useMemo(
    (): ReactionProviderValue => ({ source, actions, isTemplate, slots }),
    [source, actions, isTemplate, slots],
  );
  // ReactionsContext pairs string IDs with templates; the pages keep that pairing.
  const legacyValue = useMemo(
    () =>
      ({
        reactionId,
        isTemplate,
        isViewOnly: actions === undefined,
        ViewDeleteButtonsComponent: slots.ViewDeleteButtons,
        ValueLabelComponent: slots.ValueLabel,
        ViewOnlyLabelComponent: slots.ViewOnlyLabel,
      }) as ReactionsContext,
    [reactionId, isTemplate, actions, slots],
  );
  return (
    <reactionProviderContext.Provider value={value}>
      <reactionContext.Provider value={legacyValue}>{children}</reactionContext.Provider>
    </reactionProviderContext.Provider>
  );
}
```

`provider/reactionProvider.hooks.ts`:

```ts
import { useContext } from 'react';
import { useSyncExternalStoreWithSelector } from 'use-sync-external-store/with-selector';
import type { ReactionPathComponents } from 'common/types/reaction/reactionPathComponents.ts';
import type { ReactionInput } from 'store/entities/reactions/reactionsInputs/reactionInputs.types.ts';
import type { PreviewStatesById } from 'store/entities/reactions/reactionsPreviews/reactionsPreviews.types.ts';
import { getDeepReactionPart } from 'store/entities/reactions/reactions.utils.ts';
import { shallowEqualArrays, shallowEqualRecords } from './equality.ts';
import { orderInputs } from './orderInputs.ts';
import { reactionProviderContext } from './reactionProvider.context.ts';
import type {
  ReactionActions,
  ReactionProviderValue,
  ReactionSlots,
  ReactionSnapshot,
} from './reactionProvider.types.ts';

function useProviderValue(): ReactionProviderValue {
  const value = useContext(reactionProviderContext);
  if (!value) {
    throw new Error('Reaction hooks must be used inside a ReactionProvider.');
  }
  return value;
}

function useSnapshotSelector<T>(
  select: (snapshot: ReactionSnapshot | undefined) => T,
  isEqual?: (a: T, b: T) => boolean,
): T {
  const { source } = useProviderValue();
  return useSyncExternalStoreWithSelector(
    source.subscribe,
    source.getSnapshot,
    source.getSnapshot,
    select,
    isEqual,
  );
}

/** The whole reaction; re-renders whenever any part of it changes. */
export function useReactionSnapshot(): ReactionSnapshot | undefined {
  return useSnapshotSelector(snapshot => snapshot);
}

/** The part of the reaction at `pathComponents`, or null if the path does not exist. */
export function useReactionPart<T = unknown>(pathComponents: ReactionPathComponents): T | null {
  return useSnapshotSelector(snapshot =>
    snapshot ? ((getDeepReactionPart(snapshot.data, pathComponents) ?? null) as T | null) : null,
  );
}

/** The reaction's inputs in display order. */
export function useOrderedInputs(): Array<ReactionInput> {
  return useSnapshotSelector(
    snapshot => orderInputs(snapshot?.data.inputs ?? {}),
    shallowEqualArrays,
  );
}

/** The previews for `entityIds`; an ID with no preview maps to undefined. */
export function usePreviews(entityIds: Array<string>): PreviewStatesById {
  const { source } = useProviderValue();
  return useSyncExternalStoreWithSelector(
    source.subscribe,
    source.getPreviews,
    source.getPreviews,
    previews =>
      Object.fromEntries(entityIds.map(id => [id, previews[id]])) as PreviewStatesById,
    shallowEqualRecords,
  );
}

/** The reaction's edit actions, or undefined when it is read-only. */
export function useReactionActions(): ReactionActions | undefined {
  return useProviderValue().actions;
}

export function useIsViewOnly(): boolean {
  return useProviderValue().actions === undefined;
}

export function useReactionSlots(): ReactionSlots {
  return useProviderValue().slots;
}
```

If `getDeepReactionPart` returns `undefined` for a missing leaf (it reduces with
`part[key]`, which yields `undefined` on the last step and throws only on deeper
steps), the `?? null` keeps the hook's contract of `null`.

- [ ] **Step 6: Run the tests**

Run: `cd ~/ord/ord-app/frontend/apps/editor && npx vitest run src/features/reactions/provider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/features/reactions/provider frontend/apps/editor/package.json frontend/package-lock.json
git commit -m "Add ReactionProvider and the hooks that read a reaction through it"
```

### Task 13: The Redux source and actions, and the contract suite

**Files:**

- Create: `apps/editor/src/store/entities/reactions/reduxReactionSource.ts`,
  `apps/editor/src/store/entities/reactions/reduxReactionSource.test.tsx`

**Interfaces:**

- Consumes: Task 11's types; Task 12's provider and hooks.
- Produces:
  - `function reduxReactionSource(store: Pick<Store<AppState>, 'getState' | 'subscribe'>, reactionId: ReactionId): ReactionSource`
  - `function reduxReactionActions(dispatch: ThunkDispatch<AppState, never, Action>, reactionId: ReactionId): ReactionActions`

- [ ] **Step 1: Failing tests**

`reduxReactionSource.test.tsx`:

```tsx
import { configureStore, type Action, type ThunkDispatch } from '@reduxjs/toolkit';
import { act, render, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ReactionProvider } from 'features/reactions/provider/ReactionProvider.tsx';
import {
  usePreviews,
  useReactionPart,
  useReactionSnapshot,
} from 'features/reactions/provider/reactionProvider.hooks.ts';
import type { ReactionSlots } from 'features/reactions/provider/reactionProvider.types.ts';
import type { AppState } from 'store/configureAppStore.ts';
import { rootReducer } from 'store/rootReducer.ts';
import { emptyReactionData } from 'test/renderInReactionView.tsx';
import { addUpdateReactionFieldActions } from './reactions.actions.ts';
import { setPreviewsByIds } from './reactionsPreviews/reactionsPreviews.actions.ts';
import { reduxReactionActions, reduxReactionSource } from './reduxReactionSource.ts';

const Empty = () => null;
const slots: ReactionSlots = { ViewDeleteButtons: Empty, ValueLabel: Empty, ViewOnlyLabel: Empty };

function makeStore() {
  const reaction = (id: number | string) => ({
    id,
    data: emptyReactionData(),
    previews: {},
    summary: { provenance: {}, summary: {}, conditions: '' },
  });
  return configureStore({
    reducer: rootReducer,
    preloadedState: {
      entities: {
        reactions: {
          reactionsById: { 1: reaction(1), 2: reaction(2), template_3: reaction('template_3') },
        },
      },
    } as unknown as AppState,
  });
}

describe('reduxReactionSource', () => {
  it('returns the stored reaction, the same object until it changes', () => {
    const store = makeStore();
    const source = reduxReactionSource(store, 1);
    const before = source.getSnapshot();
    expect(before).toBe(store.getState().entities.reactions.reactionsById[1]);
    store.dispatch(
      addUpdateReactionFieldActions.request({
        reactionId: 2,
        pathComponents: ['notes'],
        newValue: { safetyNotes: 'unrelated' },
      }),
    );
    expect(source.getSnapshot()).toBe(before);
    store.dispatch(
      addUpdateReactionFieldActions.request({
        reactionId: 1,
        pathComponents: ['notes'],
        newValue: { safetyNotes: 'gloves' },
      }),
    );
    expect(source.getSnapshot()).not.toBe(before);
  });

  it('reads templates by their string IDs', () => {
    const store = makeStore();
    expect(reduxReactionSource(store, 'template_3').getSnapshot()?.data).toBeDefined();
  });

  it('notifies subscribers when the store changes, and stops after unsubscribing', () => {
    const store = makeStore();
    const listener = vi.fn();
    const unsubscribe = reduxReactionSource(store, 1).subscribe(listener);
    store.dispatch(setPreviewsByIds({ a: { isLoading: false, svg: 'A' } }));
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.dispatch(setPreviewsByIds({ b: { isLoading: false, svg: 'B' } }));
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('hooks over the Redux source', () => {
  function setup(reactionId: number | string = 1) {
    const store = makeStore();
    const source = reduxReactionSource(store, reactionId);
    function Wrapper({ children }: Readonly<{ children: ReactNode }>) {
      return (
        <ReactionProvider reactionId={reactionId} source={source} slots={slots}>
          {children}
        </ReactionProvider>
      );
    }
    return { store, wrapper: Wrapper };
  }

  it('match the static source for the same snapshot', () => {
    const { store, wrapper } = setup();
    const stored = store.getState().entities.reactions.reactionsById[1];
    expect(renderHook(useReactionSnapshot, { wrapper }).result.current).toBe(stored);
    expect(renderHook(() => useReactionPart(['notes']), { wrapper }).result.current).toBe(
      stored.data.notes,
    );
  });

  it('update when previews arrive after the first render', () => {
    const { store, wrapper } = setup();
    const { result } = renderHook(() => usePreviews(['a']), { wrapper });
    expect(result.current).toEqual({ a: undefined });
    act(() => {
      store.dispatch(setPreviewsByIds({ a: { isLoading: false, svg: 'A' } }));
    });
    expect(result.current).toEqual({ a: { isLoading: false, svg: 'A' } });
  });

  it('do not re-render a part reader when another reaction changes', () => {
    const { store, wrapper } = setup();
    let renders = 0;
    function NotesReader() {
      renders += 1;
      useReactionPart(['notes']);
      return null;
    }
    render(<NotesReader />, { wrapper });
    const rendersAfterMount = renders;
    act(() => {
      store.dispatch(
        addUpdateReactionFieldActions.request({
          reactionId: 2,
          pathComponents: ['notes'],
          newValue: { safetyNotes: 'unrelated' },
        }),
      );
    });
    expect(renders).toBe(rendersAfterMount);
  });

  it('work for a template', () => {
    const { wrapper } = setup('template_3');
    expect(renderHook(useReactionSnapshot, { wrapper }).result.current?.data).toBeDefined();
  });
});

describe('reduxReactionActions', () => {
  it('dispatch the field update and delete thunks for the reaction', async () => {
    const dispatch = vi.fn((_thunk: unknown) => Promise.resolve());
    const actions = reduxReactionActions(
      dispatch as unknown as ThunkDispatch<AppState, never, Action>,
      1,
    );
    await actions.update(['notes'], { safetyNotes: 'gloves' });
    await actions.remove(['identifiers', 0]);
    expect(dispatch).toHaveBeenCalledTimes(2);
    expect(dispatch.mock.calls.every(([thunk]) => typeof thunk === 'function')).toBe(true);
  });
});
```

Before running, open `reactionsPreviews.actions.ts` and confirm the action that stores
rendered previews and its payload shape; adjust `setPreviewsByIds(...)` calls to match.
Confirm the `notes` field names against `ReactionNotes`.

Run: `npx vitest run src/store/entities/reactions/reduxReactionSource.test.tsx`
Expected: FAIL, module missing.

- [ ] **Step 2: Implement**

`reduxReactionSource.ts`:

```ts
import type { Action, Store, ThunkDispatch } from '@reduxjs/toolkit';
import type {
  ReactionActions,
  ReactionSource,
} from 'features/reactions/provider/reactionProvider.types.ts';
import type { AppState } from 'store/configureAppStore.ts';
import { selectReactionById } from './reactions.selectors.ts';
import { addUpdateReactionField, deleteReactionField } from './reactions.thunks.ts';
import type { ReactionId } from './reactions.types.ts';
import { selectReactionsPreviews } from './reactionsPreviews/reactionsPreviews.selectors.ts';

/** Reads one reaction, dataset or template, and the rendered previews from the editor's store. */
export function reduxReactionSource(
  store: Pick<Store<AppState>, 'getState' | 'subscribe'>,
  reactionId: ReactionId,
): ReactionSource {
  return {
    getSnapshot: () => selectReactionById(reactionId)(store.getState()),
    getPreviews: () => selectReactionsPreviews(store.getState()),
    subscribe: listener => store.subscribe(listener),
  };
}

/** Edits one reaction through the thunks that apply a change optimistically and save it. */
export function reduxReactionActions(
  dispatch: ThunkDispatch<AppState, never, Action>,
  reactionId: ReactionId,
): ReactionActions {
  return {
    update: (pathComponents, newValue) =>
      dispatch(addUpdateReactionField({ reactionId, pathComponents, newValue })),
    remove: pathComponents => dispatch(deleteReactionField({ reactionId, pathComponents })),
  };
}
```

`getSnapshot` and `getPreviews` are new closures per source, but they return the
store's own objects, so `useSyncExternalStore` sees stable values. Pages create one
source per reaction with `useMemo`.

Run the test. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/store/entities/reactions/reduxReactionSource.ts \
  frontend/apps/editor/src/store/entities/reactions/reduxReactionSource.test.tsx
git commit -m "Adapt the editor's store to the reaction source and actions"
```

### Task 14: Hold the provider directory to the package's rules

**Files:**

- Modify: `frontend/eslint.config.mjs`

- [ ] **Step 1: Add the block**

```js
  {
    files: ['apps/editor/src/features/reactions/provider/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                'react-redux',
                '@reduxjs/toolkit',
                'axios',
                '@auth0/*',
                'wouter',
                'store/configureAppStore*',
                'store/useAppDispatch*',
                'store/axiosInstance*',
                'store/**/*.selectors*',
                'store/**/*.thunks*',
                'store/**/*.actions*',
                'store/**/*.reducer*',
              ],
              allowTypeImports: true,
              message:
                'The provider moves into the shared package in step G; keep it free of the store.',
            },
          ],
        },
      ],
    },
  },
```

Test files (`*.test.ts(x)`) in the directory may need store fixtures; if one does, add
`ignores: ['**/*.test.{ts,tsx}']` to the block rather than weakening the patterns.

- [ ] **Step 2: Prove it fires, then commit**

Plant `import { useSelector } from 'react-redux';` in `reactionProvider.hooks.ts`; run
`npm run lint`; expect the error; remove it.

```bash
cd ~/ord/ord-app && git add frontend/eslint.config.mjs
git commit -m "Keep the reaction provider free of the editor's store"
```

### Task 15: Wire the reaction and template pages to the provider

**Files:**

- Create: `apps/editor/src/pages/ReactionPage/useDatasetReactionProviderProps.ts`,
  `apps/editor/src/pages/ReactionPage/useDatasetReactionProviderProps.test.tsx`
- Modify: `apps/editor/src/pages/ReactionPage/ReactionPage.tsx`,
  `apps/editor/src/pages/TemplatePage/TemplatePage.tsx`

**Interfaces:**

- Consumes: `ReactionProvider`, `reduxReactionSource`, `reduxReactionActions`.
- Produces: `useDatasetReactionProviderProps(reactionId: number, canEdit: boolean): { reactionId: number; source: ReactionSource; actions?: ReactionActions; slots: ReactionSlots }`

- [ ] **Step 1: Failing test**

`useDatasetReactionProviderProps.test.tsx`:

```tsx
import { configureStore } from '@reduxjs/toolkit';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { Provider } from 'react-redux';
import { ReactionEditDeleteButtons } from 'features/reactions/ReactionInteractions/ReactionViewDeleteButtons/ReactionEditDeleteButtons.tsx';
import { ReactionViewButton } from 'features/reactions/ReactionInteractions/ReactionViewDeleteButtons/ReactionViewButton.tsx';
import { rootReducer } from 'store/rootReducer.ts';
import { useDatasetReactionProviderProps } from './useDatasetReactionProviderProps.ts';

function wrapper({ children }: Readonly<{ children: ReactNode }>) {
  return <Provider store={configureStore({ reducer: rootReducer })}>{children}</Provider>;
}

describe('useDatasetReactionProviderProps', () => {
  it('gives an editable dataset actions and the edit buttons', () => {
    const { result } = renderHook(() => useDatasetReactionProviderProps(1, true), { wrapper });
    expect(result.current.actions).toBeDefined();
    expect(result.current.slots.ViewDeleteButtons).toBe(ReactionEditDeleteButtons);
  });

  it('gives a read-only dataset no actions and the view button', () => {
    const { result } = renderHook(() => useDatasetReactionProviderProps(1, false), { wrapper });
    expect(result.current.actions).toBeUndefined();
    expect(result.current.slots.ViewDeleteButtons).toBe(ReactionViewButton);
  });

  it('keeps the same source and actions across renders', () => {
    const { result, rerender } = renderHook(() => useDatasetReactionProviderProps(1, true), {
      wrapper,
    });
    const first = result.current;
    rerender();
    expect(result.current.source).toBe(first.source);
    expect(result.current.actions).toBe(first.actions);
    expect(result.current.slots).toBe(first.slots);
  });
});
```

Run it. Expected: FAIL, module missing.

- [ ] **Step 2: Implement the hook**

`useDatasetReactionProviderProps.ts`:

```ts
import { useMemo } from 'react';
import { useStore } from 'react-redux';
import type {
  ReactionActions,
  ReactionSlots,
  ReactionSource,
} from 'features/reactions/provider/reactionProvider.types.ts';
import { DatasetReactionValueLabel } from 'features/reactions/ReactionInteractions/ReactionValueLabel/DatasetReactionValueLable.tsx';
import { ReactionEditDeleteButtons } from 'features/reactions/ReactionInteractions/ReactionViewDeleteButtons/ReactionEditDeleteButtons.tsx';
import { ReactionViewButton } from 'features/reactions/ReactionInteractions/ReactionViewDeleteButtons/ReactionViewButton.tsx';
import type { AppState } from 'store/configureAppStore.ts';
import {
  reduxReactionActions,
  reduxReactionSource,
} from 'store/entities/reactions/reduxReactionSource.ts';
import { useAppDispatch } from 'store/useAppDispatch.ts';

const EDITABLE_SLOTS: ReactionSlots = {
  ViewDeleteButtons: ReactionEditDeleteButtons,
  ValueLabel: DatasetReactionValueLabel,
  ViewOnlyLabel: DatasetReactionValueLabel,
};

const VIEW_ONLY_SLOTS: ReactionSlots = {
  ...EDITABLE_SLOTS,
  ViewDeleteButtons: ReactionViewButton,
};

/** The ReactionProvider props for a dataset reaction, editable when the user may edit it. */
export function useDatasetReactionProviderProps(
  reactionId: number,
  canEdit: boolean,
): {
  reactionId: number;
  source: ReactionSource;
  actions?: ReactionActions;
  slots: ReactionSlots;
} {
  const store = useStore<AppState>();
  const dispatch = useAppDispatch();
  const source = useMemo(() => reduxReactionSource(store, reactionId), [store, reactionId]);
  const actions = useMemo(
    () => (canEdit ? reduxReactionActions(dispatch, reactionId) : undefined),
    [canEdit, dispatch, reactionId],
  );
  return { reactionId, source, actions, slots: canEdit ? EDITABLE_SLOTS : VIEW_ONLY_SLOTS };
}
```

Run the test. Expected: PASS.

- [ ] **Step 3: `ReactionPage.tsx`**

- Delete the `reactionContextValue` `useMemo`, the `isViewOnly` constant, and the
  now-unused imports (`reactionContext`, `ReactionsContext`,
  `ReactionEditDeleteButtons`, `ReactionViewButton`, `DatasetReactionValueLabel`).
- Add
  `const providerProps = useDatasetReactionProviderProps(reactionId, canDatasetBeEdited);`
  next to the other hooks, before any early return.
- Replace `<reactionContext.Provider value={reactionContextValue}>` and its closing tag
  with `<ReactionProvider {...providerProps}>` and `</ReactionProvider>`.

- [ ] **Step 4: `TemplatePage.tsx`**

Add at module scope:

```ts
const TEMPLATE_SLOTS: ReactionSlots = {
  ViewDeleteButtons: ReactionSetVariablesButton,
  ValueLabel: TemplateReactionValueLabelWrapper,
  ViewOnlyLabel: DatasetReactionValueLabel,
};
```

Replace the `reactionContextValue` `useMemo` with

```ts
const store = useStore<AppState>();
const source = useMemo(() => reduxReactionSource(store, templateId), [store, templateId]);
```

(before the early return), and the provider element with
`<ReactionProvider reactionId={templateId} isTemplate source={source} slots={TEMPLATE_SLOTS}>`.
Remove the unused `reactionContext` and `ReactionsContext` imports.

- [ ] **Step 5: The editor's suite is unchanged**

```bash
cd ~/ord/ord-app/frontend
(cd apps/editor && npx vitest run 2>&1 | tail -5)
npm run lint:check && npm run typecheck
```

Expected: every pre-existing test passes with its assertions untouched; the new tests
add to the count.

- [ ] **Step 6: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/src/pages/ReactionPage frontend/apps/editor/src/pages/TemplatePage
git commit -m "Render the reaction and template pages under ReactionProvider"
```

### Task 16: Playwright: the reaction page, its drawer, and screenshots

**Files:**

- Create: `apps/editor/e2e/fixtures/reaction.pbtxt`, `apps/editor/e2e/seed.ts`,
  `apps/editor/e2e/reactionPage.spec.ts`
- Modify: `.github/workflows/tests.yml` (upload the snapshot directory on failure)

**Interfaces:**

- Produces: `seedReaction(request: APIRequestContext): Promise<{ datasetId: number; reactionId: number }>`

- [ ] **Step 1: The fixture**

`apps/editor/e2e/fixtures/reaction.pbtxt`:

```text
identifiers { type: REACTION_SMILES value: "CC(=O)O.NCc1ccccc1>>CC(=O)NCc1ccccc1" }
inputs {
  key: "acid"
  value {
    components {
      identifiers { type: SMILES value: "CC(=O)O" }
      amount { moles { value: 1 units: MILLIMOLE } }
      reaction_role: REACTANT
    }
  }
}
inputs {
  key: "amine"
  value {
    components {
      identifiers { type: SMILES value: "NCc1ccccc1" }
      amount { moles { value: 1.2 units: MILLIMOLE } }
      reaction_role: REACTANT
    }
  }
}
conditions { temperature { setpoint { value: 25 units: CELSIUS } } }
outcomes {
  reaction_time { value: 2 units: HOUR }
  products {
    identifiers { type: SMILES value: "CC(=O)NCc1ccccc1" }
    is_desired_product: true
    measurements { type: YIELD percentage { value: 85 } }
    reaction_role: PRODUCT
  }
}
```

- [ ] **Step 2: Seeding through the API**

`apps/editor/e2e/seed.ts`. In e2e mode the backend accepts any bearer token as the dev
user (`ord_app/service_api/services/auth0.py`):

```ts
import type { APIRequestContext } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const API = process.env.VITE_API_ENDPOINT ?? 'http://127.0.0.1:8000/service_api/api/v1';
const headers = { Authorization: 'Bearer e2e-dev-token' };

async function post<T>(request: APIRequestContext, url: string, options: object): Promise<T> {
  const response = await request.post(`${API}${url}`, { headers, ...options });
  if (!response.ok()) {
    throw new Error(`POST ${url} returned ${response.status()}: ${await response.text()}`);
  }
  return (await response.json()) as T;
}

/** Creates a group, a dataset in it, and the fixture reaction, as the e2e dev user. */
export async function seedReaction(
  request: APIRequestContext,
): Promise<{ datasetId: number; reactionId: number }> {
  await request.post(`${API}/auth/jit-provisioning`, { headers });
  const group = await post<{ id: number }>(request, '/groups', {
    data: { name: `e2e reaction page ${Date.now()}` },
  });
  const dataset = await post<{ id: number }>(request, `/groups/${group.id}/datasets`, {
    data: { name: 'Reaction page' },
  });
  const reaction = await post<{ id: number }>(
    request,
    `/datasets/${dataset.id}/reactions/upload`,
    {
      multipart: {
        file: {
          name: 'reaction.pbtxt',
          mimeType: 'text/plain',
          buffer: readFileSync(path.join(import.meta.dirname, 'fixtures', 'reaction.pbtxt')),
        },
      },
    },
  );
  return { datasetId: dataset.id, reactionId: reaction.id };
}
```

Check `/auth/jit-provisioning`'s method and status in
`ord_app/service_api/resources/v1/auth.py` before relying on it; the UI calls it on
load, so mirror what `src/` sends (search for `jit-provisioning`).

- [ ] **Step 3: The flows**

`apps/editor/e2e/reactionPage.spec.ts`:

```ts
import { expect, test } from '@playwright/test';
import { seedReaction } from './seed.ts';

let reactionUrl: string;

test.beforeAll(async ({ request }) => {
  const { datasetId, reactionId } = await seedReaction(request);
  reactionUrl = `/datasets/${datasetId}/reactions/${reactionId}`;
});

test.beforeEach(async ({ page }) => {
  await page.goto(reactionUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('acid', { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });
});

test('switches between the tabs and list views', async ({ page }) => {
  await page.getByText('List', { exact: true }).click();
  await expect(page.getByRole('radio', { name: 'List' })).toBeChecked();
  await page.getByText('Tabs', { exact: true }).click();
  await expect(page.getByRole('radio', { name: 'Tabs' })).toBeChecked();
});

test('opens an entity in the drawer and closes it', async ({ page }) => {
  await page.getByRole('button', { name: 'Edit' }).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
});

test('looks the same', async ({ page }) => {
  test.skip(!process.env.CI, 'Screenshots are compared only in CI, where the baselines are made.');
  await expect(page).toHaveScreenshot('reaction-page.png', {
    fullPage: true,
    mask: [page.getByRole('navigation')],
  });
  await page.getByRole('button', { name: 'Edit' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page).toHaveScreenshot('reaction-drawer.png');
});
```

Run against the local stack (`scripts/dev-e2e.sh`, then
`cd frontend/apps/editor && npx playwright test e2e/reactionPage.spec.ts`). Expected:
the first two tests PASS and the third is skipped. If a locator does not match, read
the rendered page with `npx playwright test --debug` and fix the locator, not the
component. If the drawer does not close on Escape, close it with its close button.

- [ ] **Step 4: CI baselines**

In `tests.yml`, add `frontend/apps/editor/e2e/*-snapshots/` to the failure upload's
`path` list. Push the branch; the first `test_e2e` run fails with "A snapshot doesn't
exist" and writes the baselines. Download the `playwright-report` artifact, inspect the
PNGs for content that changes between runs (IDs, timestamps); add each such element to
`mask`. Commit the PNGs under `apps/editor/e2e/reactionPage.spec.ts-snapshots/`, push,
and confirm the next run passes. Re-run the job once more to confirm the screenshots
are stable.

- [ ] **Step 5: Commit**

```bash
cd ~/ord/ord-app
git add frontend/apps/editor/e2e .github/workflows/tests.yml
git commit -m "Cover the reaction page and its drawer in Playwright"
```

### Task 17: Open PR A

- [ ] **Step 1: Full check**

```bash
cd ~/ord/ord-app/frontend
npm run lint:check && npm run typecheck && npm run test:coverage && npm run build
cd .. && frontend/node_modules/.bin/jscpd --config .jscpd.json
```

- [ ] **Step 2: Push and open**

```bash
git push -u origin reaction-provider
gh pr create --title "Add ReactionProvider and render the reaction pages under it" \
  --body-file "$SCRATCH/a-body.md"
```

The body says no component reads the hooks yet, the provider supplies the old context
so nothing changes on screen, and the Playwright screenshots are the guard for steps B
through G.

---

## After A: steps B through G

Each gets its own plan once A merges, written against the code A leaves. From the
design:

| Step | Plan scope |
| --- | --- |
| B | Display reads move to the hooks: the nine sections, previews, header, validation results, cards. Wrap the dataset list's cards in `ReactionProvider`. Decide how `CrudeComponentView` links to another reaction (a `links` provider value). |
| C | The drawer's stack moves from `features.reactionForm` into the provider; `useDrawer()`. |
| D | Form reads move to the hooks. |
| E | Edits go through `useReactionActions()`, including the compound lookup and the current person; the lookup flags move to local state; read-only drawers lose the Delete icon. |
| F | The preview worker becomes a plain module; the static source renders previews. |
| G | Move the provider, `renderWithReaction`, the reaction view, the shell, the icons, `ReactionComponentPreview`, `renderValuePrecisionUnit`, `AppReaction`, and its converters into `packages/ui`; `PageContainer` takes header slots; Ketcher in the drawer becomes a lazy import; retire `reactionContext`. |

## Refinements to the design

These came from reading the code while planning; the design file has been updated to
match.

- **W is two PRs.** W1 only moves files and configuration, so its review is
  mechanical; W2 holds the package's real decisions.
- **W2 moves less.** The theme and four display primitives (`KeyValueDisplay`,
  `RequiredOptionalFields`, `DataField`, `Counter`) have no store dependencies.
  `ReactionComponentPreview` imports a store type and `renderValuePrecisionUnit` an
  editor hook, so both move in G, with the icons. The package gains a `./display`
  export for the primitives.
- **One Vitest config per workspace, not Vitest projects.** Vitest applies coverage
  options at the root of a projects run, so separate floors per package are simpler as
  separate runs; the root `test:coverage` script runs each.
- **The snapshot is the stored object.** `ReactionSnapshot` keeps the store's field
  names (`pb_reaction_id`, `is_valid`), so the Redux source returns the store's own
  object and stays referentially stable without memoization. `useReactionMeta` becomes
  `useReactionSnapshot`.
- **Re-rendering matches today's, not finer.** The reducer rebuilds a reaction's `data`
  with a deep merge on every edit, so an edit re-renders every reader of that reaction,
  as `useSelector` does now. The hooks keep that behavior and do not re-render readers
  of other reactions.
- **A wires only the pages.** The list cards and the `links` value move to B, where
  their first consumers are.
- **The provider lives in the editor until G**, in
  `features/reactions/provider/`, with a lint rule that keeps it free of the store.
- **A tests read-only wiring below the browser.** `useDatasetReactionProviderProps` and
  the hook tests cover it; the Playwright check that a read-only dataset shows no edit or
  Delete controls moves to E, which is when read-only behavior changes. Seeding a
  read-only dataset needs a second user and group roles, which E's plan sets up.
- **A's contract tests use small fixtures.** The full-reaction fixture from #837 is
  for B and D, when components render real parts of a reaction.
