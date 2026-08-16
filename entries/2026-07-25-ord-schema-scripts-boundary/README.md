# Where ord-schema ends: splitting the library from ord-data's pipeline

- **Date:** 2026-07-25
- **Author:** Steven Kearnes
- **Status:** draft (decided; migration not yet done)
- **Tags:** ord-schema, ord-data, packaging, ci, testing, refactor
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`ord_schema/scripts/` holds seven CLI scripts. Some are tools a data producer uses
against the schema; others are machinery that only ord-data's CI runs. Which is which,
and where should the new derived-views code from
[2026-07-25](../2026-07-25-derived-parquet-sidecars/README.md) live?

The organizing principle: **ord-schema should be the library.** Use cases intended for
other settings do not belong in it.

## Summary

Three of the seven scripts are ord-data pipeline or one-off ingestion code and should
move; three are genuine schema use cases with documented audiences and should stay; one
is probably dead.

The same test places the new derived-views work — definition *and* CLI — in ord-schema.
Traffic runs both ways across this boundary: ord-data sheds machinery that only it uses,
and gains none of the code for a capability its data is merely the largest instance of.

The decisive evidence is *what the documentation tells users to run*, not what the
scripts' own docstrings claim. `process_dataset.py` describes itself as "a one-stop shop
for preparing submissions," which reads as contributor-facing — but it appears **nowhere**
in the submission workflow. The documented Submit step is `cp`, `git add`, `git commit`,
`git push`; `process_dataset.py` runs afterwards, from CI, when a reviewer triggers
preprocessing. An earlier read of this took the docstring at face value and reached the
wrong conclusion.

The clearest single symptom: **ord-schema carries a `pygithub` optional dependency whose
only consumer is `process_dataset.py`**, a script that exists to service ord-data's
submission flow. A library is paying packaging weight for another repository's CI.

The blocker is that **ord-data has no Python test infrastructure at all**, and
`process_dataset_test.py` is the most thoroughly tested script in `ord_schema/scripts/`.
Moving it before standing up a harness would silently drop test coverage on the pipeline
where a bug corrupts submitted data.

## Method

Read all seven scripts and their docstrings; grepped every consumer across `ord-data`,
`ord-interface`, `ord-app`, and `ord-infrastructure`; read `docs/submissions.rst`,
`docs/schema.rst`, `docs/guides/templates.rst`, `docs/build_docs.sh`, and `README.md` in
`ord-schema`; and read `CONTRIBUTING.md` plus all three workflows in `ord-data`. Package
metadata from `ord-schema`'s `pyproject.toml`.

## Findings

### 1. Documented audience is the discriminator

| script | documented for users? | who runs it |
| --- | --- | --- |
| `validate_dataset.py` | **yes** — `submissions.rst` (Create), `schema.rst` | data producers, and ord-data CI |
| `enumerate_dataset.py` | **yes** — `templates.rst`, linked from ord-interface's editor UI | data producers |
| `build_dataset.py` | no | data producers (authoring) |
| `process_dataset.py` | **no** — only a `README.md` note about its optional dependency | ord-data CI only |
| `pb_to_parquet_dataset.py` | no | the pb→parquet migration |
| `parse_uspto.py` | no | one-off, built the uspto-grants corpus |
| `check_pb.py` | no | unclear; likely dead |

Two structural facts lower the cost of moving anything: `docs/build_docs.sh` **excludes**
`ord_schema/scripts/` from `sphinx-apidoc`, so none of these are part of the documented
Python API; and `pyproject.toml` declares **no console entry points**, so they are
invoked by path and have no packaging contract either.

### 2. `process_dataset.py` is pipeline machinery, not a contributor tool

Walking the documented workflow settles it. `submissions.rst` has four steps — Create,
Prepare, Submit, Review. `validate_dataset.py` appears under **Create**. Submit is:

```shell
cp path/to/example_dataset.pbtxt .
git add example_dataset.pbtxt
git commit -m "Example dataset submission"
git push origin my_submission
```

Then Review says a reviewer "will trigger various automated preprocessing steps, such as
renaming the dataset and assigning reaction and dataset IDs." That is
`process_dataset.py --update`, run by `submission.yml`. The contributor never invokes it.

The script's shape confirms it: `--base=upstream/main`, git-diff-driven input, and
placement of outputs under `data/` via `message_helpers.id_filename`. It is written
against one repository's layout and branch conventions.

### 3. A library dependency that exists for another repo's CI

`ord-schema`'s `README.md`:

> `github` — the GitHub-issue submission flow in `ord_schema.scripts.process_dataset`

`pygithub>=1.51` is an optional dependency of the schema library, imported by exactly one
file (`process_dataset.py:40`), to post comments on ord-data pull requests. Moving that
script lets the extra be **deleted outright** rather than merely relocated.

### 4. `validate_dataset.py` has a genuine pre-clone audience

The counter-argument for moving it is that anyone submitting data has necessarily cloned
ord-data, so co-locating costs them nothing. True at *submission* time, but the docs put
validation earlier: `validate_dataset.py` is recommended under **Create**, and the
fork-and-clone instruction does not appear until **Prepare**. The intended flow is build
programmatically → validate → *then* decide to submit.

`submissions.rst` also immediately adds that it is "good practice to use the validation
methods in `ord-schema`" — pointing at `validations.py`. So the library is already the
primary mechanism and the script is a CLI convenience over it. That is exactly what
should stay.

Its parquet row-group fan-out and `--filter` regex exist to serve ord-data's nine-way CI
matrix, but the ord-data-specific part is the *invocation*, which already lives in
`validation.yml`.

### 5. ord-data has no Python test infrastructure

No `pyproject.toml`, no pytest configuration, no test files, and no test job in any of
the three workflows. The existing `scripts/` — `convert_to_parquet.py`,
`upload_to_huggingface.py`, `download_from_huggingface.py` — are untested.

Meanwhile `process_dataset_test.py` is 29 KB, the largest test file under
`ord_schema/scripts/`. Moving the script into a repo with nowhere to run its tests would
convert a well-covered component into an uncovered one, in the pipeline that rewrites
contributor submissions.

This makes the harness a prerequisite rather than a nicety — and it is needed for the
derived-views driver regardless.

### 6. The views work is library code end to end, CLI included

Deriving views is not an ord-data use case. It is "turn ORD datasets into tabular
columns," which anyone holding ORD datasets can want: a group with a private corpus, a
reviewer checking a submission before it is merged, a downstream tool that never touches
the production repository. By the discriminator in finding 1 — is there an audience
outside ord-data? — both halves belong in the library:

- **`ord_schema/views.py`** — the view *definition*: proto → columns, the unit basis, the
  SMILES generation policy. Versioned and testable.
- **`ord_schema/scripts/derive_views.py`** — the CLI over it: take an input pattern,
  write view Parquet, stamp footers.

`ord_schema/orm/` is the precedent. It is generic machinery for loading ORD data into a
relational database, and it carries its own `ord_schema/orm/scripts/add_datasets.py`
rather than pushing that CLI into whichever repository happens to run it. Views follow
the same shape; if the definition grows past one module, it becomes a subpackage with its
own `scripts/` for the same reason.

What is genuinely ord-data-specific is the *invocation*: walk `data/`, publish to the
Hugging Face mirror, decide when to rebuild. That is a workflow, and it already lives in
`.github/workflows/` alongside the existing `validate_dataset.py` invocation — the same
arrangement finding 4 describes for validation.

This is not merely tidy. The tier-1 contract states that views are *"reproducible from
the source protos alone, with pinned open tooling (`ord-schema` + RDKit)."* A definition
reachable only by cloning a data repository would weaken the claim the whole design rests
on, and so would a CLI that only exists there — reproduction would mean reimplementing the
driver. With both in the library, reproducing a published view is `pip install
ord-schema==X` and one command, against any dataset. It also makes the derivation version
an ord-schema version, and satisfies the dataset-card obligation to state the view
definition by pointing at a versioned module.

## Conclusions / next steps

### The split

| action | scripts | rationale |
| --- | --- | --- |
| **move to `ord-data/scripts/`** | `process_dataset.py` (+ test), `pb_to_parquet_dataset.py` (+ test), `parse_uspto.py` | pipeline and one-off ingestion; no documented user audience |
| **keep in `ord-schema`** | `validate_dataset.py`, `enumerate_dataset.py`, `build_dataset.py` | documented schema use cases; `validate_dataset` has a pre-clone audience |
| **confirm dead, then delete** | `check_pb.py` | compares two deprecated formats; undocumented and unreferenced |
| **add to `ord-schema`** | `views.py`, `scripts/derive_views.py` | new code; deriving views is a schema use case, not an ord-data one (finding 6) |

### Sequence

1. **Stand up pytest and a CI job in ord-data.** Prerequisite for the moves below. Land
   it with at least one real test so the harness is proven rather than merely present.
2. **Move `process_dataset.py` with its tests intact**, then delete the `github` extra
   from `ord-schema`'s `pyproject.toml` and the corresponding `README.md` row.
3. **Move `pb_to_parquet_dataset.py` and `parse_uspto.py`**; verify `check_pb.py` is
   unreferenced and delete it.
4. **Implement the views work in ord-schema** — `views.py` and
   `scripts/derive_views.py` (finding 6). Independent of steps 1–3: it adds code rather
   than moving any, and lands in a repository that already has a test harness. ord-data
   gets only the workflow that runs the CLI over `data/` and publishes the results.

### What it buys

Beyond the principle: ord-schema sheds a dependency that only served another repo, and
ord-data's submission pipeline starts versioning with ord-data. That last point bears on
an existing oddity — ord-data pins `ORD_SCHEMA_TAG: v0.6.3` while ord-schema ships
`0.8.0`. Pinning the *library* for stable validation semantics is defensible; pinning it
to freeze ord-data's own pipeline code is not, and the move removes that coupling. Worth
confirming separately whether the two-minor-version lag is deliberate or stale.

### Not in scope

Adding console entry points (`[project.scripts]`) so ord-data can `pip install
ord-schema==X` and invoke `ord-validate-dataset` rather than checking out the repository
and running a script by path. That is the remaining coupling after this migration, it is
independent of it, and there is no packaging contract to break — but it is a separate
change.

## References

- Scripts and packaging: `ord-schema` `ord_schema/scripts/`, `pyproject.toml`
  (`[project.optional-dependencies] github`), `README.md`, `docs/build_docs.sh`
  (apidoc exclusions).
- Documented workflows: `ord-schema` `docs/submissions.rst`, `docs/schema.rst`,
  `docs/guides/templates.rst`; `ord-data` `CONTRIBUTING.md`.
- Pipeline invocations: `ord-data` `.github/workflows/submission.yml`,
  `.github/workflows/validation.yml` (both check out `ORD_SCHEMA_TAG` and run scripts by
  path).
- ord-interface's link to `enumerate_dataset.py`:
  `ord_interface/editor/html/datasets.html`.
- Companion entry: [2026-07-25 derived parquet views](../2026-07-25-derived-parquet-sidecars/README.md)
  (the tier-1 contract that motivates the library/driver split).
