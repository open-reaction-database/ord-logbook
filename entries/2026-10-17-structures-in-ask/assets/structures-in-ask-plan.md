# Structures in an /ask question: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

- **Date:** 2026-10-17
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

**Goal:** Let an `/ask` question carry structures that are drawn in Ketcher or pasted as
SMILES or SMARTS. Each one appears as a generated placeholder (`@A`) in one of three
formats, and an instructions page with examples explains how to use them.

**Architecture:**

- A new `ord_schema.search.placeholders` module holds the formats, validation,
  classification, and the substitution pass. `nl.translate` uses it to describe the
  placeholders to the model and to substitute their text into the model's query before
  validation.
- ord-app's backend validates each request's placeholders with that module. It also
  serves `POST /api/structure`, which classifies a pasted candidate and draws its
  thumbnail.
- The viewer's `/ask` page holds the question and its placeholders in the URL. Ketcher's
  dialog decides a drawing's format.

**Tech Stack:**

- **ord-schema:** Python 3.12, pydantic 2, RDKit, `anthropic`.
- **ord-app:** FastAPI and RDKit in the backend; React 19, Mantine 7, wouter 3, TanStack
  Query 5, and Ketcher in the frontend; Vitest with happy-dom and Testing Library for
  unit tests; Playwright for end-to-end tests.

**Spec:** [`structures-in-ask-design.md`](structures-in-ask-design.md). Paths are in
ord-schema at
[`cc0be34`](https://github.com/open-reaction-database/ord-schema/commit/cc0be34) and
ord-app at [`7de6638`](https://github.com/open-reaction-database/ord-app/commit/7de6638).

## Refinements to the design

These came from reading the code while planning. They settle what the design left to the
builder, and the design file stands as written.

- **One module for placeholders.** `ord_schema.search.placeholders` holds:
  - the format enum;
  - the `Placeholder` model;
  - classification and the question check;
  - the user-message lines;
  - substitution.

  ord-app's backend imports it, so the bounds and the error wording live in one place.
- **Paste parsing and thumbnails run in the backend.** `POST /api/structure` takes
  `{text, format?}`. Without a format, it classifies the text. With one, it validates
  the text as that format. It returns `{format, text, svg}`, where the SVG comes from
  RDKit.
  - "Parses" then means what the search will accept, because both use RDKit.
  - A single renderer draws all three formats, including query features and reactions,
    which the browser's molblock previews do not carry.
- **The user message.** When a question carries placeholders, a blank line and this
  block follow the question:

  ```text
  Placeholders in this question:
  @A is a compound SMILES.
  ```

  The lines are ordered by name length, then by name, so `@Z` comes before `@AA`.
- **How the dialog decides a format.**
  - A drawing with a reaction is a reaction SMARTS.
  - Otherwise, a drawing Indigo writes as SMILES with no `*` is a compound SMILES.
  - Anything else is a compound SMARTS.

  The dialog already reports "an atom list asked for as SMILES" as a failure to write
  SMILES, which is the signal this uses.
- **A wildcard makes SMARTS.** A SMILES holding a `*` atom is a compound SMARTS. A
  dummy atom matches nothing as a compound identity, but it means any atom as a
  pattern.
- **The URL.** Each placeholder is one repeated `structure` parameter, written
  `@A:compound_smarts:[c;R1]-[Br,I]` and split at its first two colons. A name and a
  format never hold a colon, but SMARTS does, in aromatic bonds and atom maps.
- **The log.** `structures` is stored as a JSON string, like `resolved`, and is left out
  of `_FREE_TEXT` for the same reason: it is what reproduces the search.
- **The examples mirror existing evaluation cases.** Each placeholder example asks a
  question the case file already answers by name or by inline structure, so its
  reference query is known to be right:

  | Example | Placeholder | Reference taken from the case |
  | --- | --- | --- |
  | which reactions use @A as a solvent? | `@A` compound SMILES `c1ccncc1` | "which reactions use pyridine as a solvent?" |
  | reactions using an input with Tanimoto similarity at least 0.6 to @A | `@A` compound SMILES `Nc1ccccc1` | "reactions using an input with Tanimoto similarity at least 0.6 to aniline" |
  | reactions with a reactant containing @A, ignoring its stereochemistry | `@A` compound SMILES `OC(=O)[C@@H]1CCCN1` | `reactions with a reactant containing OC(=O)[C@@H]1CCCN1, ignoring its stereochemistry` |
  | reactions with an input matching @A | `@A` compound SMARTS `[$([N+](=O)[O-]),$(N(=O)=O)]` | "reactions with a nitro group on any input" |
  | which reactions match @A? | `@A` reaction SMARTS `cB(O)O.c[Br,I]>>c-c` | "which reactions couple an aryl boronic acid or ester with an aryl bromide or iodide?" |
  | which reactions use @A as a solvent and have a desired product with a yield above 50%? | `@A` compound SMILES `c1ccncc1` | the `and` of the pyridine case's `where` and the case "reactions where a desired product has a yield above 50%" |
  | reactions using benzene as an input with yield greater than 70% | none | new; written in Task S4 |

  The similarity example gives a coefficient. The prompt takes a threshold only from the
  question, so "similar to @A" alone would leave the threshold to the model.

## Global Constraints

- Every source file starts with the Apache 2.0 header that addlicense writes. New files
  carry `Copyright 2026`.
- Use American English in UI text, comments, docstrings, and commit messages.
- Comments say what the code does and why, never what changed. No measured figures go in
  code or comments.
- Python:
  - Google-style docstrings with a one-line summary;
  - no lazy imports;
  - free functions rather than `@staticmethod`;
  - every `pytest.raises` gets a `match=`;
  - no abbreviated words in identifiers.
- ord-schema tests run with `.venv/bin/pytest -n auto <files>` from the repository root.
- ord-app's backend tests run with `uv run pytest -n auto` in `backend/viewer`.
- ord-app frontend:
  - Unit tests run with `npx vitest run` in `frontend/apps/viewer` and in
    `frontend/packages/ui`.
  - Type-check with `npm run typecheck` and lint with `npm run lint:check`, both from
    `frontend/`.
  - The viewer imports its own files through `#…`, never `../`, and the shared package
    only through its `exports`.
  - Coverage floors in `frontend/apps/viewer/vite.config.ts` rise to the measured value,
    rounded down, at the end of each PR.
- The bounds come from the design: at most 10 placeholders per question, and at most
  2,000 characters per placeholder text.
- The formats' API values are `compound_smiles`, `compound_smarts`, and
  `reaction_smarts`. Their labels are "compound SMILES", "compound SMARTS", and
  "reaction SMARTS".
- The question box keeps the accessible role `textbox` and the name "Question", since
  existing tests find it that way.
- PR order: ord-schema (S1–S4) in one PR, then a release through `publish.yml`, then
  ord-app (A1–A9). Each PR is green on its own.

## Review Focus

1. **Words and formulas that nearly parse.** `Pd(OAc)2`, `CO2`, `C6H6`, `Et3N`, `H2O`,
   `2-pyridone`, and `70%` stay text when pasted, while `c1ccccc1Br` becomes a
   placeholder. The test is in A6, `placeholders.test.ts`, and the backend half is in
   A2.
2. **SMARTS punctuation through the URL and JSON.** `[C;R]Cl`, `[c:1]Br`, `[#6&R]`,
   `[Br,I]`, and `C(=O)Cl.N>>C(=O)N` round-trip exactly. The tests are in A6,
   `placeholders.test.ts`, and in A1.
3. **Markers beside punctuation and inside other text.** `(@A)`, `@A,`, and `@A's` are
   markers. `[C@@H]`, `C[C@H](O)`, and `user@Example.com` are not. The tests are in S1
   and A6.
4. **A paste holding more structures than the bound.** The first 10 become placeholders
   and the rest stay text, with the note saying so. The test is in A7,
   `AskPage.test.tsx`.
5. **Asking again after editing a structure.** A changed structure under the same
   question asks again rather than showing the cached answer, and Back restores the
   earlier structure. The tests are in A6, `hooks.test.ts`, and A7,
   `AskPage.test.tsx`.

---

## Part 1: ord-schema

### Task S1: The placeholders module

**Files:**

- Create: `ord_schema/search/placeholders.py`
- Test: `ord_schema/search/placeholders_test.py`

**Interfaces:**

- Consumes: `query.Substructure`, `query.SameCompound`, and `query.ReactionSmarts`,
  which validate a structure's text.
- Produces:
  - `StructureFormat(enum.StrEnum)`: `COMPOUND_SMILES = "compound_smiles"`,
    `COMPOUND_SMARTS = "compound_smarts"`, and `REACTION_SMARTS = "reaction_smarts"`.
    Its `label` property returns `"compound SMILES"`, `"compound SMARTS"`, or
    `"reaction SMARTS"`.
  - `Placeholder(BaseModel)`, frozen with `extra="forbid"`, with fields
    `format: StructureFormat` and `text: str`.
  - `PlaceholderError(ValueError)`.
  - Constants: `MOST_PLACEHOLDERS = 10`, `MOST_CHARACTERS = 2000`, and
    `PLACEHOLDERS_HEADING = "Placeholders in this question:"`.
  - Functions:
    - `is_name(value: object) -> bool`
    - `markers(question: str) -> set[str]`
    - `classify(text: str) -> Placeholder`
    - `check(question: str, structures: Mapping[str, Placeholder]) -> None`
    - `describe(structures: Mapping[str, Placeholder]) -> str`
    - `substitute(value: Any, structures: Mapping[str, Placeholder]) -> Any`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_placeholder_is_validated_by_its_format():
    assert placeholders.Placeholder(format="compound_smiles", text="c1ccncc1")
    with pytest.raises(ValidationError, match="SMILES does not parse"):
        placeholders.Placeholder(format="compound_smiles", text="c1ccnc")
    with pytest.raises(ValidationError, match="wildcard"):
        placeholders.Placeholder(format="compound_smiles", text="c1ccccc1*")
    with pytest.raises(ValidationError, match="SMARTS has no atoms"):
        placeholders.Placeholder(format="compound_smarts", text="")
    with pytest.raises(ValidationError, match="at most 5 are supported"):
        placeholders.Placeholder(format="reaction_smarts", text="C.C.C.C.C.C>>C")
    with pytest.raises(ValidationError, match="at most 2000 characters"):
        placeholders.Placeholder(format="compound_smiles", text="C" * 2001)

@pytest.mark.parametrize(
    "text,expected",
    [
        ("c1ccccc1Br", "compound_smiles"),
        ("c1ccccc1*", "compound_smarts"),
        ("[c;R1]-[Br,I]", "compound_smarts"),
        ("C(=O)Cl.N>>C(=O)N", "reaction_smarts"),
    ],
)
def test_classify(text, expected):
    assert placeholders.classify(text) == placeholders.Placeholder(format=expected, text=text)

@pytest.mark.parametrize("text", ["2-pyridone", "Pd(OAc)2", "CO2", "70%"])
def test_classify_refuses_what_is_not_a_structure(text):
    with pytest.raises(placeholders.PlaceholderError, match="not a SMILES, SMARTS, or reaction SMARTS"):
        placeholders.classify(text)

def test_markers():
    assert placeholders.markers("make (@A) from @B, and @AA's yield") == {"@A", "@B", "@AA"}
    assert placeholders.markers("[C@@H] and C[C@H](O) from user@Example.com") == set()

def test_check():
    smiles = placeholders.Placeholder(format="compound_smiles", text="CCO")
    placeholders.check("reactions using @A", {"@A": smiles})
    placeholders.check("reactions using ethanol", {})
    with pytest.raises(placeholders.PlaceholderError, match="@B is in the question but has no structure"):
        placeholders.check("reactions using @A and @B", {"@A": smiles})
    with pytest.raises(placeholders.PlaceholderError, match="@B has a structure but is not in the question"):
        placeholders.check("reactions using @A", {"@A": smiles, "@B": smiles})
    with pytest.raises(placeholders.PlaceholderError, match="'@a' is not a placeholder name"):
        placeholders.check("reactions using @a", {"@a": smiles})
    many = {f"@{letter}": smiles for letter in "ABCDEFGHIJK"}
    with pytest.raises(placeholders.PlaceholderError, match="at most 10 placeholders"):
        placeholders.check(" ".join(many), many)

def test_describe():
    assert placeholders.describe({}) == ""
    assert placeholders.describe({
        "@AA": placeholders.Placeholder(format="reaction_smarts", text="C>>C"),
        "@B": placeholders.Placeholder(format="compound_smarts", text="[Br,I]"),
    }) == (
        "Placeholders in this question:\n"
        "@B is a compound SMARTS.\n"
        "@AA is a reaction SMARTS."
    )

def test_substitute_moves_text_into_the_field_each_predicate_takes():
    structures = {
        "@A": placeholders.Placeholder(format="compound_smiles", text="c1ccncc1"),
        "@B": placeholders.Placeholder(format="compound_smarts", text="c[Br,I]"),
        "@E": placeholders.Placeholder(format="reaction_smarts", text="cB(O)O.c[Br,I]>>c-c"),
    }
    query = {"where": {"op": "and", "clauses": [
        {"op": "same_compound", "path": "smiles", "compound": "@A"},
        {"op": "substructure", "path": "smiles", "smiles": "@A"},
        {"op": "substructure", "path": "smiles", "compound": "@B"},
        {"op": "reaction_smarts", "smarts": "@E"},
    ]}}
    assert placeholders.substitute(query, structures)["where"]["clauses"] == [
        {"op": "same_compound", "path": "smiles", "smiles": "c1ccncc1"},
        {"op": "substructure", "path": "smiles", "smarts": "c1ccncc1"},
        {"op": "substructure", "path": "smiles", "smarts": "c[Br,I]"},
        {"op": "reaction_smarts", "smarts": "cB(O)O.c[Br,I]>>c-c"},
    ]

@pytest.mark.parametrize(
    "clause,message",
    [
        ({"op": "similarity", "path": "smiles", "compound": "@B", "threshold": 0.6},
         "@B is a compound SMARTS, which similarity does not take; similarity takes a compound SMILES"),
        ({"op": "same_compound", "path": "smiles", "compound": "@D"},
         "@D is not a placeholder in this question"),
        ({"op": "reaction_smarts", "smarts": "@A>>@B"}, "@A appears in reaction_smarts"),
        ({"op": "eq", "path": "smiles", "value": {"literal": "@A"}}, "@A appears in eq"),
    ],
)
def test_substitute_refuses(clause, message):
    structures = {
        "@A": placeholders.Placeholder(format="compound_smiles", text="CCO"),
        "@B": placeholders.Placeholder(format="compound_smarts", text="c[Br,I]"),
    }
    with pytest.raises(placeholders.PlaceholderError, match=re.escape(message)):
        placeholders.substitute({"where": clause}, structures)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest -n auto ord_schema/search/placeholders_test.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ord_schema.search.placeholders'`

- [ ] **Step 3: Implement `ord_schema/search/placeholders.py`**

- **Names and markers.** A name matches `@[A-Z]+` in full. A marker in a question
  matches `(?<![\w@])@[A-Z]+(?!\w)`.
- **Validation** runs in an `after` model validator:
  - the length check comes first;
  - a compound SMILES goes through `query.SameCompound` with `smiles`, then is refused
    if any atom has atomic number 0;
  - a compound SMARTS goes through `query.Substructure` with `smarts`;
  - a reaction SMARTS goes through `query.ReactionSmarts`.

  The grammar's messages pass through unchanged.
- **`classify` order:**
  - text holding `>` is a reaction SMARTS;
  - otherwise, `Chem.MolFromSmiles` with atoms and no atomic number 0 is a compound
    SMILES;
  - otherwise, `Chem.MolFromSmarts` with atoms is a compound SMARTS;
  - anything else raises
    `PlaceholderError(f"{text!r} is not a SMILES, SMARTS, or reaction SMARTS")`.

  RDKit's parse errors are silenced with `rdBase.BlockLogs()`.
- **`check`'s messages:**
  - `f"{name!r} is not a placeholder name: write @ and capital letters, such as @A"`
  - `f"a question holds at most {MOST_PLACEHOLDERS} placeholders, and this one has {count}"`
  - `f"{name} is in the question but has no structure"`
  - `f"{name} has a structure but is not in the question"`
- **`substitute`** walks dicts and lists and returns a new value.
  - A dict whose `op` is one of `substructure`, `similarity`, `same_compound`,
    `same_parent`, or `reaction_smarts` may hold a name as the whole value of
    `compound`, `smiles`, or `smarts`.
  - Each such name is replaced by its text under `smarts` (for `substructure` and
    `reaction_smarts`) or `smiles` (for the others), and the original key is removed.
  - The formats each op takes are:
    - `substructure`: compound SMILES or compound SMARTS;
    - `similarity`, `same_compound`, `same_parent`: compound SMILES;
    - `reaction_smarts`: reaction SMARTS.
  - Any other string holding a marker raises
    `f"{name} appears in {op or key}, but a placeholder is only the whole value of compound, smiles, or smarts in substructure, similarity, same_compound, same_parent, or reaction_smarts"`.
  - Other errors:
    - an unbound name: `f"{name} is not a placeholder in this question; the placeholders are {listed or 'none'}"`;
    - a wrong format: `f"{name} is a {format.label}, which {op} does not take; {op} takes a {' or a '.join(labels)}"`.

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/bin/pytest -n auto ord_schema/search/placeholders_test.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ord_schema/search/placeholders.py ord_schema/search/placeholders_test.py
git commit -m "Add placeholders for structures in a question"
```

### Task S2: Placeholders in translation

**Files:**

- Modify: `ord_schema/search/nl.py` (`translate`, `ask`, and the `judged` closure)
- Modify: `ord_schema/search/nl_prompt.md`, after the bullet "Name compounds rather than
  spelling structures"
- Test: `ord_schema/search/nl_test.py`

**Interfaces:**

- Consumes: all of S1.
- Produces:
  - `translate(question, *, structures: Mapping[str, placeholders.Placeholder] | None = None, ...)`
  - `ask(question, corpus, *, structures: Mapping[str, placeholders.Placeholder] | None = None, ...)`

  Both raise `placeholders.PlaceholderError` before any model call when `check` fails.

- [ ] **Step 1: Write the failing tests** in `nl_test.py`, with `_StubClient` and the
  module's `corpus`:

```python
_PYRIDINE = placeholders.Placeholder(format="compound_smiles", text="c1ccncc1")

def _uses(slot):
    return {"where": {"op": "exists", "path": "inputs.components", "where": slot}}

def test_placeholders_follow_the_question():
    client = _StubClient(_uses({"op": "same_compound", "path": "smiles", "compound": "@A"}))
    nl.translate("reactions using @A", structures={"@A": _PYRIDINE}, client=client)
    assert client.requests[0]["messages"][0]["content"] == (
        "reactions using @A\n\nPlaceholders in this question:\n@A is a compound SMILES."
    )

def test_a_question_without_placeholders_is_sent_alone():
    client = _StubClient({"where": _SOLVENT})
    nl.translate("reactions run in a solvent", client=client)
    assert client.requests[0]["messages"][0]["content"] == "reactions run in a solvent"

def test_a_placeholder_is_substituted_and_the_attempt_keeps_it():
    client = _StubClient(_uses({"op": "same_compound", "path": "smiles", "compound": "@A"}))
    translated = nl.translate("reactions using @A", structures={"@A": _PYRIDINE}, client=client)
    clause = translated.query.where.where
    assert (clause.smiles, clause.compound) == ("c1ccncc1", None)
    assert translated.attempts[0].translation["where"]["where"]["compound"] == "@A"

def test_a_format_the_predicate_refuses_is_handed_back():
    pattern = placeholders.Placeholder(format="compound_smarts", text="c[Br,I]")
    client = _StubClient(
        _uses({"op": "similarity", "path": "smiles", "compound": "@B", "threshold": 0.6}),
        _uses({"op": "substructure", "path": "smiles", "compound": "@B"}),
    )
    translated = nl.translate("inputs like @B", structures={"@B": pattern}, client=client)
    assert "@B is a compound SMARTS, which similarity does not take" in translated.attempts[0].error
    assert translated.turns == 2

def test_an_unbound_placeholder_never_reaches_the_resolver(corpus):
    client = _StubClient(
        _uses({"op": "same_compound", "path": "smiles", "compound": "@D"}),
        _uses({"op": "same_compound", "path": "smiles", "compound": "@D"}),
    )
    with pytest.raises(nl.MalformedQueryError, match="@D is not a placeholder"):
        nl.ask("reactions using @A", corpus, structures={"@A": _PYRIDINE}, client=client)

def test_a_question_that_fails_the_check_makes_no_call():
    client = _StubClient()
    with pytest.raises(placeholders.PlaceholderError, match="@A is in the question but has no structure"):
        nl.translate("reactions using @A", client=client)
    assert client.requests == []

def test_ask_searches_with_the_placeholder(corpus):
    client = _StubClient(
        _uses({"op": "same_compound", "path": "smiles", "compound": "@A"}),
        "One reaction uses @A.",
    )
    answer = nl.ask("reactions using @A", corpus, structures={"@A": _PYRIDINE}, client=client)
    assert answer.table.column("reaction_id").to_pylist() == ["ord-nl01"]
    assert answer.query.where.where.smiles == "c1ccncc1"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_test.py -k placeholder`
Expected: FAIL with `TypeError: translate() got an unexpected keyword argument 'structures'`

- [ ] **Step 3: Implement it in `nl.py`**

- `translate` first calls `placeholders.check(question, structures or {})`.
- The first message is `question`, followed by `"\n\n" + placeholders.describe(structures)`
  when there are any.
- In `judged`, `_validated` receives `placeholders.substitute(coerced, structures or {})`
  inside the existing `try`. `PlaceholderError` is a `ValueError`, so it already becomes
  the rejection, while the `Attempt` records `coerced`.
- `ask` passes `structures` through to `translate`. Its `Raises:` section gains
  `PlaceholderError`.

- [ ] **Step 4: Add the prompt bullet** to `nl_prompt.md`, after the bullet that begins
  "Name compounds rather than spelling structures":

```markdown
- A question can carry structures the user drew or pasted, as placeholders such as `@A`,
  listed after the question with each one's format. Write a placeholder's name, exactly
  and alone, where its structure goes: `"compound": "@A"` in `substructure`,
  `similarity`, `same_compound`, or `same_parent`, and `"smarts": "@E"` in
  `reaction_smarts`. It is not a compound name, and you never write out the structure it
  stands for. Pick the predicate from the wording, as for a named compound: `@A` alone
  is `same_compound`, "containing @A" is `substructure`, "similar to @A" is
  `similarity`, and "@A, whichever salt" is `same_parent`. A compound SMILES fits all
  four; a compound SMARTS fits only `substructure`; a reaction SMARTS fits only
  `reaction_smarts`. A question asking a placeholder for what its format cannot do —
  "similar to @B" where `@B` is a compound SMARTS — gets `cannot_answer` naming the
  format, not a different search.
```

- [ ] **Step 5: Run the module's tests**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_test.py ord_schema/search/placeholders_test.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ord_schema/search/nl.py ord_schema/search/nl_prompt.md ord_schema/search/nl_test.py
git commit -m "Translate questions that carry placeholders"
```

### Task S3: Placeholders in the question log

**Files:**

- Modify: `ord_schema/search/nl_log.py` (`Ask`, `event`, `_COLUMNS`)
- Modify: `ord_schema/search/nl.py` (`ask`'s `record`)
- Test: `ord_schema/search/nl_log_test.py`, `ord_schema/search/nl_test.py`

**Interfaces:**

- Consumes: S2's `ask(structures=...)`.
- Produces: `nl_log.Ask.structures: Mapping[str, Mapping[str, str]] | None = None`. The
  `ask` event's `"structures"` is a JSON string sorted by key, or `None` when the
  question carried none.

- [ ] **Step 1: Write the failing tests**

```python
# nl_log_test.py
def test_the_structures_are_written_as_a_string():
    structures = {"@A": {"format": "compound_smiles", "text": "c1ccncc1"}}
    event = nl_log.event(_ask(structures=structures))
    assert json.loads(event["structures"]) == structures
    assert nl_log.event(_ask())["structures"] is None

def test_structures_survive_redacted_compaction_beside_records_without_them(tmp_path):
    structures = {"@A": {"format": "compound_smiles", "text": "c1ccncc1"}}
    sink = nl_log.JsonlSink(tmp_path / "raw" / "log.jsonl")
    sink.write(nl_log.event(_ask(record_id="0001", structures=structures)))
    sink.write(nl_log.event(_ask(record_id="0002")))
    older = nl_log.event(_ask(record_id="0003"))
    del older["structures"]
    sink.write(older)
    compacted = tmp_path / "2026-10.parquet"
    nl_log.compact(str(tmp_path / "raw" / "*.jsonl"), compacted, redact=True)
    for source in (str(tmp_path / "raw" / "*.jsonl"), str(compacted)):
        rows = nl_log.read(
            source, statement="SELECT record_id, structures FROM log ORDER BY record_id"
        ).fetchall()
        assert rows == [
            ("0001", '{"@A": {"format": "compound_smiles", "text": "c1ccncc1"}}'),
            ("0002", None),
            ("0003", None),
        ]

# nl_test.py
def test_ask_records_its_structures(corpus):
    sink = _CollectingSink()
    client = _StubClient(_uses({"op": "same_compound", "path": "smiles", "compound": "@A"}), "One.")
    nl.ask("reactions using @A", corpus, structures={"@A": _PYRIDINE}, client=client, sink=sink)
    assert json.loads(sink.events[0]["structures"]) == {"@A": {"format": "compound_smiles", "text": "c1ccncc1"}}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_log_test.py ord_schema/search/nl_test.py -k structures`
Expected: FAIL with `TypeError: Ask.__init__() got an unexpected keyword argument 'structures'`

- [ ] **Step 3: Implement it**

- Add the `Ask` field, documented beside `resolved`.
- Add `"structures": "VARCHAR"` to `_COLUMNS`, and leave it out of `_FREE_TEXT`.
- `ask`'s `record` passes
  `structures={name: p.model_dump(mode="json") for name, p in structures.items()} or None`.

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_log_test.py ord_schema/search/nl_test.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ord_schema/search/nl_log.py ord_schema/search/nl_log_test.py ord_schema/search/nl.py ord_schema/search/nl_test.py
git commit -m "Record a question's placeholders in the log"
```

### Task S4: Evaluation cases with placeholders

**Files:**

- Modify: `ord_schema/search/nl_eval.py` (`EvalCase`, `run_case`)
- Modify: `ord_schema/search/nl_cases.json`
- Test: `ord_schema/search/nl_eval_test.py`

**Interfaces:**

- Consumes: S2's `translate(structures=...)` and S3's `Ask.structures`.
- Produces: `EvalCase.structures: dict[str, placeholders.Placeholder] = {}`, checked
  against the question with `placeholders.check` when the case is built. The
  instructions page in A8 copies the questions and placeholders of these cases.

- [ ] **Step 1: Write the failing tests**

`_StubClient` gains a `requests` list that `create` appends each request to, if it has
none.

```python
def test_a_case_carries_its_placeholders_to_the_model():
    case = nl_eval.EvalCase(
        question="which reactions use @A as a solvent?",
        why="a compound SMILES placeholder",
        structures={"@A": {"format": "compound_smiles", "text": "c1ccncc1"}},
        reference={"where": {"op": "not_null", "path": "reaction_id"}},
    )
    client = _StubClient("build_query", {"where": {
        "op": "exists", "path": "inputs.components",
        "where": {"op": "same_compound", "path": "smiles", "compound": "@A"}}})
    _run(case, client)
    assert client.requests[0]["messages"][0]["content"].endswith(
        "Placeholders in this question:\n@A is a compound SMILES."
    )

def test_a_case_whose_placeholders_do_not_fit_its_question_is_refused():
    with pytest.raises(ValidationError, match="@B is in the question but has no structure"):
        nl_eval.EvalCase(question="reactions using @B", why="x", compiles=False)

def test_the_case_file_loads():
    cases = nl_eval.load_cases()
    assert sum(bool(case.structures) for case in cases) == 8
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_eval_test.py`
Expected: FAIL with `ValidationError` for the unknown field `structures`

- [ ] **Step 3: Implement it**

- `EvalCase` gains `structures`, plus a validator that calls `placeholders.check`.
- `run_case` passes `structures=case.structures` to `nl.translate`, and records them the
  way `ask` does.
- Add eight cases to `nl_cases.json`:
  - the six placeholder examples from the Refinements table, each reusing the
    reference named there;
  - "reactions using an input similar to @A with Tanimoto similarity at least 0.6",
    where `@A` is the compound SMARTS `c[Br,I]`, with `compiles: false`;
  - "reactions that use @A as a reactant", where `@A` is the reaction SMARTS
    `cB(O)O.c[Br,I]>>c-c`, with `compiles: false`.

  Also add the name-only example "reactions using benzene as an input with yield
  greater than 70%". Its reference is an `exists` over `inputs.components` with
  `same_compound` on `c1ccccc1`, combined with `and` and an `exists` over
  `outcomes.products` holding a `YIELD` measurement with `percentage.value` `gt` 70.

- [ ] **Step 4: Check that every new reference returns reactions from the local corpus**

Run this from the repository root with the repository `.venv`, using the projections
and structures globs under `~/ord/artifacts` that the `nl_eval` command takes:

```bash
.venv/bin/python -I - "$PROJECTIONS" "$STRUCTURES" <<'EOF'
import sys
from ord_schema.search import execute, nl_eval, query
with execute.Corpus(sys.argv[1], sys.argv[2]) as corpus:
    for case in nl_eval.load_cases():
        if case.reference is not None and (case.structures or "benzene" in case.question):
            table = corpus.search(query.Query.model_validate(case.reference))
            print(table.num_rows, case.question)
EOF
```

Expected: every line starts with a number above 0. If a case returns none, choose a
structure that the corpus holds, and change the matching row of the Refinements table
in the logbook plan.

- [ ] **Step 5: Run them to see them pass**

Run: `.venv/bin/pytest -n auto ord_schema/search/nl_eval_test.py ord_schema/search/nl_test.py ord_schema/search/nl_log_test.py ord_schema/search/placeholders_test.py`
Expected: PASS

- [ ] **Step 6: Commit, and open the ord-schema PR**

```bash
git add ord_schema/search/nl_eval.py ord_schema/search/nl_eval_test.py ord_schema/search/nl_cases.json
git commit -m "Evaluate questions that carry placeholders"
```

Once it merges, ord-app waits for the release that `publish.yml` makes.

---

## Part 2: ord-app

### Task A1: Placeholders in /api/ask

**Files:**

- Modify: `backend/viewer/pyproject.toml` and `backend/viewer/uv.lock`, pinning
  `ord-schema[huggingface,nl,search]` to the release that holds S1–S4
- Modify: `backend/viewer/ord_viewer/routes/ask.py`
- Modify: `backend/viewer/openapi.json`, regenerated with `python -m ord_viewer.openapi`
- Test: `backend/viewer/ord_viewer/routes/ask_test.py`

**Interfaces:**

- Consumes: `placeholders.Placeholder`, `placeholders.check`, and
  `nl.ask(structures=...)`.
- Produces: `AskRequest.structures: dict[str, Placeholder]`, defaulting to `{}`. The
  frontend's generated `AskRequest` gains it in A6.

- [ ] **Step 1: Write the failing tests**

```python
def _input(op, **slot):
    return {"where": {"op": "exists", "path": "inputs.components",
                      "where": {"op": op, "path": "smiles", **slot}}}

def test_answers_a_question_with_a_placeholder(client, ask_with):
    stub = ask_with(_input("same_compound", compound="@A"), "One reaction.")
    response = client.post("/api/ask", json={
        "question": "reactions using @A",
        "structures": {"@A": {"format": "compound_smiles", "text": "c1ccncc1"}},
    })
    assert response.status_code == 200
    assert "Placeholders in this question:" in stub.requests[0]["messages"][0]["content"]
    assert response.json()["query"]["where"]["where"]["smiles"] == "c1ccncc1"

@pytest.mark.parametrize("body,message", [
    ({"question": "reactions using @A"}, "@A is in the question but has no structure"),
    ({"question": "reactions", "structures": {"@A": {"format": "compound_smiles", "text": "CCO"}}},
     "@A has a structure but is not in the question"),
    ({"question": "reactions using @A", "structures": {"@A": {"format": "compound_smiles", "text": "c1ccnc"}}},
     "SMILES does not parse"),
])
def test_refuses_placeholders_before_asking(client, ask_with, body, message):
    stub = ask_with()
    response = client.post("/api/ask", json=body)
    assert response.status_code == 422
    assert message in json.dumps(response.json())
    assert stub.requests == []

def test_smarts_punctuation_reaches_the_query_unchanged(client, ask_with):
    # Review Focus 2.
    ask_with(_input("substructure", compound="@A"), "None.")
    text = "[#6&R;!$(C=O)]-[Cl,Br]"
    response = client.post("/api/ask", json={
        "question": "reactions using @A",
        "structures": {"@A": {"format": "compound_smarts", "text": text}},
    })
    assert response.json()["query"]["where"]["where"]["smarts"] == text
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -n auto ord_viewer/routes/ask_test.py`
Expected: FAIL (422 "extra inputs are not permitted" for `structures`)

- [ ] **Step 3: Implement it**

- `AskRequest` gains `structures`, bounded to `MOST_PLACEHOLDERS` entries, with a
  `model_validator(mode="after")` that calls `placeholders.check` and raises its
  message as a `ValueError`.
- The route passes `structures=body.structures` to `nl.ask`.
- The `ASK_ERRORS` 422 description gains "or its placeholders do not fit it".
- Regenerate `openapi.json`.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest -n auto`
Expected: PASS, `openapi_test` included

- [ ] **Step 5: Commit**

```bash
git add backend/viewer/pyproject.toml backend/viewer/uv.lock backend/viewer/ord_viewer/routes/ask.py backend/viewer/ord_viewer/routes/ask_test.py backend/viewer/openapi.json
git commit -m "Take placeholders with a question in /api/ask"
```

### Task A2: /api/structure

**Files:**

- Create: `backend/viewer/ord_viewer/routes/structure.py`
- Modify: `backend/viewer/ord_viewer/main.py`, to include the router beside the others
- Modify: `backend/viewer/openapi.json`
- Test: `backend/viewer/ord_viewer/routes/structure_test.py`

**Interfaces:**

- Consumes: `placeholders.classify` and `placeholders.Placeholder`.
- Produces: `POST /api/structure`. The request is
  `StructureRequest {text: str, format: StructureFormat | None = None}`. The response is
  `StructureResponse {format: StructureFormat, text: str, svg: str}`. It answers 422
  with the placeholder error when the text is not a structure.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("text,expected", [
    ("c1ccccc1Br", "compound_smiles"),
    ("[c;R1]-[Br,I]", "compound_smarts"),
    ("C(=O)Cl.N>>C(=O)N", "reaction_smarts"),
])
def test_classifies_and_draws(client, text, expected):
    body = client.post("/api/structure", json={"text": text}).json()
    assert (body["format"], body["text"]) == (expected, text)
    assert body["svg"].startswith("<?xml") and "</svg>" in body["svg"]

def test_a_given_format_is_checked_not_inferred(client):
    response = client.post("/api/structure", json={"text": "[c;R1]-[Br,I]", "format": "compound_smiles"})
    assert response.status_code == 422

@pytest.mark.parametrize("text", ["Pd(OAc)2", "CO2", "C6H6", "Et3N", "H2O", "2-pyridone", "70%"])
def test_words_are_not_structures(client, text):
    # Review Focus 1, the backend's half.
    assert client.post("/api/structure", json={"text": text}).status_code == 422
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -n auto ord_viewer/routes/structure_test.py`
Expected: FAIL with 404

- [ ] **Step 3: Implement it**

- `structure_svg(placeholder: Placeholder) -> str` lives in `structure.py` and draws
  with `rdMolDraw2D.MolDraw2DSVG(200, 150)`:
  - `DrawReaction` for a reaction SMARTS;
  - `DrawMolecule` of `MolFromSmiles` or `MolFromSmarts` for the compound formats.
- The route is synchronous, so FastAPI runs it in a worker thread.
- Regenerate `openapi.json`.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest -n auto`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/viewer/ord_viewer/routes/structure.py backend/viewer/ord_viewer/routes/structure_test.py backend/viewer/ord_viewer/main.py backend/viewer/openapi.json
git commit -m "Classify and draw a candidate structure"
```

### Task A3: Scripted questions with placeholders

**Files:**

- Modify: `backend/viewer/ord_viewer/testing.py` (`ScriptedAskClient`, `ASK_SCRIPTS`)
- Test: `backend/viewer/ord_viewer/testing_test.py`

**Interfaces:**

- Consumes: `placeholders.PLACEHOLDERS_HEADING`.
- Produces: scripts that A9's end-to-end tests ask:
  - "reactions that use @A": `same_compound` with `"compound": "@A"`, answered "Three
    reactions use @A.";
  - "reactions with an input matching @A": `substructure` with `"compound": "@A"`;
  - "which reactions match @A?": `reaction_smarts` with `"smarts": "@A"`.

  Each orders by `reaction_id`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_scripted_client_answers_a_question_with_placeholders(corpus_dir):
    client = make_client(corpus_dir, ask_client=ScriptedAskClient(ASK_SCRIPTS))
    response = client.post("/api/ask", json={
        "question": "reactions that use @A",
        "structures": {"@A": {"format": "compound_smiles", "text": "CC(=O)Cl"}},
    })
    assert [row["reaction_id"] for row in response.json()["result"]["reactions"]] == [
        "ord-viewer0102", "ord-viewer0103", "ord-viewer0201",
    ]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest -n auto ord_viewer/testing_test.py`
Expected: FAIL; the scripted client declines with "no script"

- [ ] **Step 3: Implement it**

- `ScriptedAskClient` looks up `text.split("\n\n" + placeholders.PLACEHOLDERS_HEADING, 1)[0]`.
- Add the three scripts.
- Confirm against the fixture corpus that the acyl chloride SMARTS `[CX3](=O)Cl` and
  the reaction SMARTS `C(=O)Cl.N>>C(=O)N` each return reactions. Write those IDs into
  A9's assertions.

- [ ] **Step 4: Run it to see it pass**

Run: `uv run pytest -n auto`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/viewer/ord_viewer/testing.py backend/viewer/ord_viewer/testing_test.py
git commit -m "Script questions with placeholders for the end-to-end tests"
```

### Task A4: The Ketcher dialog decides a drawing's format

**Files:**

- Modify: `frontend/packages/ui/src/ketcher/structure.types.ts`,
  `frontend/packages/ui/src/ketcher/KetcherDialog.tsx`, and
  `frontend/packages/ui/src/ketcher/index.ts`
- Test: `frontend/packages/ui/src/ketcher/KetcherDialog.test.tsx`

**Interfaces:**

- Produces:

```ts
export type DrawnFormat = 'compound_smiles' | 'compound_smarts' | 'reaction_smarts';
export interface DrawnStructure { format: DrawnFormat; text: string }
export const DRAWN_FORMAT_LABELS: Record<DrawnFormat, string>; // 'compound SMILES', …
// StructureDialogProps becomes a union. The existing branch is unchanged; the new one is
// { format: 'detect'; onSave: (structure: DrawnStructure) => void } with the same other props.
```

- [ ] **Step 1: Write the failing tests.** The stub gains
  `containsReaction: vi.fn(() => false)`, and its `aromatize` can be made to reject
  `DaylightSmiles`.
  - `it('saves a drawing Indigo writes as SMILES as a compound SMILES')`: `onSave` is
    called with `{format: 'compound_smiles', text: 'aromatic chemical/x-daylight-smiles'}`.
  - `it('saves a drawing that cannot be SMILES as a compound SMARTS')`: `aromatize`
    rejects SMILES with "atom list", and `onSave` gets `format: 'compound_smarts'`.
  - `it('saves a SMILES holding a wildcard as a compound SMARTS')`: the SMILES reply is
    `'c1ccccc1*'`.
  - `it('saves a reaction as a reaction SMARTS')`: `containsReaction` returns true, so
    the SMILES writer is never asked.
  - `it('names the format it will save as')`: after `change(true)`, the footer shows
    "compound SMILES".

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/ketcher/KetcherDialog.test.tsx` in `frontend/packages/ui`
Expected: FAIL

- [ ] **Step 3: Implement it**

`detect(ketcher)` follows the rule in the Refinements:

```ts
async function detect(ketcher: Ketcher): Promise<DrawnStructure> {
  if (ketcher.containsReaction()) {
    return { format: 'reaction_smarts', text: await aromatized(ketcher, ChemicalMimeType.DaylightSmarts) };
  }
  try {
    const text = await aromatized(ketcher, ChemicalMimeType.DaylightSmiles);
    if (!text.includes('*')) {
      return { format: 'compound_smiles', text };
    }
  } catch {
    // Indigo refuses to write query features as SMILES; they are SMARTS.
  }
  return { format: 'compound_smarts', text: await aromatized(ketcher, ChemicalMimeType.DaylightSmarts) };
}
```

- In detect mode, the dialog runs `detect` on each canvas change, keeping the latest
  result, and shows `DRAWN_FORMAT_LABELS[format]` beside `children`. Save calls
  `onSave(await detect(ketcher))`.
- The fixed-format branch keeps today's behavior.

- [ ] **Step 4: Run the package's tests and the type check**

Run: `npx vitest run` in `frontend/packages/ui`, then `npm run typecheck` from `frontend/`
Expected: PASS. The search form's fixed-format callers still type-check.

- [ ] **Step 5: Commit**

```bash
git add frontend/packages/ui/src/ketcher/
git commit -m "Let the structure dialog decide a drawing's format"
```

### Task A5: The API types and hooks

**Files:**

- Modify: `frontend/apps/viewer/src/api/schema.ts`, regenerated with
  `npm run generate:api`
- Modify: `frontend/apps/viewer/src/api/types.ts` and
  `frontend/apps/viewer/src/api/hooks.ts`
- Test: `frontend/apps/viewer/src/api/hooks.test.ts`

**Interfaces:**

- Consumes: A1's and A2's OpenAPI document.
- Produces:
  - the types `StructureRequest`, `StructureResponse`, `StructureFormat`, and
    `Structures = Record<string, { format: StructureFormat; text: string }>`;
  - `useAsk(question: string | null, structures: Structures)`, keyed on
    `['ask', question, structures]`;
  - `useStructure(text: string, format?: StructureFormat)`, keyed on
    `['structure', text, format ?? null]`, which posts to `/api/structure`.

- [ ] **Step 1: Write the failing tests**
  - `it('asks with the question and its structures')`: the body posted to `/api/ask`
    equals `{question, structures}`.
  - `it('asks again when a structure changes')` (Review Focus 5): two renders with the
    same question and different text for `@A` make two requests.
  - `it('classifies a structure')`: `useStructure('c1ccccc1Br')` posts `{text}` and
    returns the response.

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/api/hooks.test.ts` in `frontend/apps/viewer`
Expected: FAIL

- [ ] **Step 3: Regenerate `schema.ts` and implement the types and hooks**

- [ ] **Step 4: Run them to see them pass**

Run: `npx vitest run src/api` in `frontend/apps/viewer`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/viewer/src/api/
git commit -m "Ask with structures, and classify a candidate structure"
```

### Task A6: Placeholder logic for the page

**Files:**

- Create: `frontend/apps/viewer/src/ask/placeholders.ts`
- Test: `frontend/apps/viewer/src/ask/placeholders.test.ts`

**Interfaces:**

- Produces:

```ts
export const MOST_PLACEHOLDERS = 10;
export const MOST_CHARACTERS = 2000;
export function nextName(used: ReadonlySet<string>): string; // '@A' … '@Z', '@AA', …
export function markers(question: string): string[];        // in order of appearance, distinct
export function candidates(text: string): Array<{ start: number; end: number; token: string }>;
export function encodeStructures(structures: Structures): string[]; // values for repeated `structure`
export function decodeStructures(values: readonly string[]): Structures;
```

- [ ] **Step 1: Write the failing tests**
  - `nextName`:
    - returns `@A` for an empty set and `@B` after `@A`;
    - returns `@AA` after `@A`…`@Z`;
    - never reuses a name that is in `used` but missing from the question.
  - `markers` (Review Focus 3):
    - `'make (@A) from @B, and @A\'s yield'` gives `['@A', '@B']`;
    - `'[C@@H] and C[C@H](O) from user@Example.com'` gives `[]`.
  - `candidates` (Review Focus 1):
    - `'reactions making c1ccccc1Br.'` gives one candidate, `c1ccccc1Br`, with the period
      left out;
    - `'CO I No THF benzene @A'` gives `[]`, since no token holds a candidate character;
    - `'Pd(OAc)2 CO2 C6H6 Et3N H2O 2-pyridone 70%'` gives all seven tokens. The
      lexical rule only nominates tokens, and the backend's parse in A2 turns these
      away.
  - The encoding round trip (Review Focus 2):
    `decodeStructures(encodeStructures(s))` equals `s` for texts `[C;R]Cl`, `[c:1]Br`,
    `[#6&R]`, `[Br,I]`, and `C(=O)Cl.N>>C(=O)N`. `encodeStructures` writes
    `@A:compound_smarts:[c;R1]-[Br,I]`.

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/ask/placeholders.test.ts` in `frontend/apps/viewer`
Expected: FAIL

- [ ] **Step 3: Implement it**

- Markers use `/(?<![\w@])@[A-Z]+(?!\w)/g`, the same rule as S1's.
- A candidate is a whitespace-separated token, after the trailing characters
  `. , ; : ? !` are removed, that holds one of the digits or `[ ] ( ) = # + / \ >`.
- Decoding splits each value at its first two colons, and drops a value whose name or
  format does not fit.

- [ ] **Step 4: Run them to see them pass**

Run: `npx vitest run src/ask` in `frontend/apps/viewer`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/viewer/src/ask/placeholders.ts frontend/apps/viewer/src/ask/placeholders.test.ts
git commit -m "Name, find, and encode placeholders"
```

### Task A7: The /ask page with placeholders

**Files:**

- Create: `frontend/apps/viewer/src/ask/QuestionBox.tsx`,
  `frontend/apps/viewer/src/ask/PlaceholderList.tsx`, and a test for each
- Modify: `frontend/apps/viewer/src/pages/AskPage.tsx` and
  `frontend/apps/viewer/src/pages/AskPage.test.tsx`

**Interfaces:**

- Consumes: A4's `StructureDialog` in detect mode, A5's hooks, and A6's functions.
- Produces:
  - `QuestionBox({value, onChange, structures, onPasteText})`, with these types:
    - `value: string`, the question with its markers as plain text;
    - `onChange(value: string): void`;
    - `structures: Structures`;
    - `onPasteText(text: string, start: number, end: number): void`, which receives
      pasted text and the selection it replaces, so the page decides what the paste
      becomes.

    It has role `textbox` and the name "Question", and shows each marker as a token
    with a thumbnail in its format's color: blue for compound SMILES, amber for
    compound SMARTS, and purple for reaction SMARTS. An unbound marker shows as
    undefined.
  - `PlaceholderList({structures, inQuestion, onEdit, onInsert, onRemove})`. Each row
    has the thumbnail (from `useStructure(text, format)`), the name, the format label,
    the text, and Edit, Insert, and ✕. A reaction's row is full width.

- [ ] **Step 1: Write the failing tests** in `AskPage.test.tsx`, which already renders
  with `renderAt`:
  - `it('turns a pasted SMILES into a placeholder, with undo')`: pasting
    `reactions making c1ccccc1Br` (with `/api/structure` stubbed to `compound_smiles`)
    leaves the box holding `reactions making @A`. The row shows "compound SMILES". Undo
    restores the text and removes the row.
  - `it('leaves text the backend does not read as a structure')`: `/api/structure`
    answers 422 for `Et3N`, and the text stays.
  - `it('converts the first ten structures of a long paste and says so')` (Review Focus
    4): pasting 12 SMILES makes `@A`…`@J`. The note names the two left as text.
  - `it('disables Ask for an undefined marker')`: typing `@D` shows "@D isn't defined.
    Draw it, or remove it from the question." and disables Ask.
  - `it('keeps a removed row out of the request but lets Insert restore it')`.
  - `it('puts the question and its structures in the URL')`: asking navigates to
    `/ask?q=…&structure=@A:compound_smiles:c1ccccc1Br`.
  - `it('restores the structures from the URL on Back')` (Review Focus 5).
  - `it('converts a typed SMILES when Ask is pressed')`.
  - `it('draws a structure as the next placeholder')`: the dialog stub saves
    `{format: 'compound_smarts', text: '[c;R1]-[Br,I]'}`, and `@A` is inserted at the
    cursor.

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/pages/AskPage.test.tsx` in `frontend/apps/viewer`
Expected: FAIL

- [ ] **Step 3: Implement it.**
  - The page reads `q` and every `structure` parameter from the URL, and asks with
    `useAsk(question, structures)` for the markers that appear in the question.
  - The paste handler finds candidates with A6's `candidates` and checks each with
    `/api/structure`, at most 10 per question in all.
  - **Draw structure** opens `StructureDialog` in detect mode, with "Saves as @D" (the
    next name) as its `children`. **Edit** opens it on the row's text and keeps the
    name.
  - `QuestionBox` may use a `contenteditable` with atomic token spans, or another
    approach that keeps role `textbox`, the name "Question", and the plain-text value
    with markers.
  - The three example buttons stay.

- [ ] **Step 4: Run the viewer's tests and checks**

Run: `npx vitest run`, then `npm run typecheck` and `npm run lint:check` from `frontend/`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/viewer/src/ask/ frontend/apps/viewer/src/pages/AskPage.tsx frontend/apps/viewer/src/pages/AskPage.test.tsx
git commit -m "Draw and paste structures into an /ask question"
```

### Task A8: The instructions page

**Files:**

- Create: `frontend/apps/viewer/src/ask/examples.ts`,
  `frontend/apps/viewer/src/pages/AskHelpPage.tsx`, and
  `frontend/apps/viewer/src/pages/AskHelpPage.test.tsx`
- Modify: `frontend/apps/viewer/src/routes.tsx` and
  `frontend/apps/viewer/src/pages/AskPage.tsx`, adding links from beside the box and
  from the development note

**Interfaces:**

- Consumes: A6's `encodeStructures` and A5's `useStructure`, for the drawings.
- Produces: `ASK_HELP_EXAMPLES: ReadonlyArray<{question: string; structures: Structures; shows: string}>`,
  which holds the seven rows of the Refinements table in that order.

- [ ] **Step 1: Write the failing tests**
  - `it('is reached from /ask')`: the "How to ask" link leads to `/ask/help`.
  - `it('lists every example with its structures drawn')`: there are seven examples,
    and each placeholder shows its format label.
  - `it('tries an example')`: Try it on the reaction SMARTS example navigates to
    `/ask?q=which+reactions+match+%40A%3F&structure=…`.
  - `it('explains the formats and their limits')`: the page holds "compound SMILES",
    "compound SMARTS", "reaction SMARTS", "five templates", and "similarity".

- [ ] **Step 2: Run them to see them fail**

Run: `npx vitest run src/pages/AskHelpPage.test.tsx` in `frontend/apps/viewer`
Expected: FAIL

- [ ] **Step 3: Implement it.** The page holds the sections from the design's "The
  instructions page", in that order:
  1. what `/ask` does;
  2. naming compounds;
  3. drawing and pasting;
  4. the three formats and the wording that picks each search;
  5. limits, linking the cartridge note as the search page's help note does;
  6. examples.

  Add the `/ask/help` route before `/ask`.

- [ ] **Step 4: Run the viewer's tests and checks**

Run: `npx vitest run`, `npm run typecheck`, and `npm run lint:check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/viewer/src/ask/examples.ts frontend/apps/viewer/src/pages/AskHelpPage.tsx frontend/apps/viewer/src/pages/AskHelpPage.test.tsx frontend/apps/viewer/src/routes.tsx frontend/apps/viewer/src/pages/AskPage.tsx
git commit -m "Add instructions and examples for /ask"
```

### Task A9: End-to-end tests and coverage

**Files:**

- Modify: `frontend/apps/viewer/e2e/ask.spec.ts` and
  `frontend/apps/viewer/vite.config.ts` (the coverage floors)

**Interfaces:**

- Consumes: A3's scripts and the fixture corpus.

- [ ] **Step 1: Write the tests**
  - `test('asks with a pasted compound SMILES')`: paste `reactions that use CC(=O)Cl`
    into the Question box. Expected: the box shows `@A`, the row shows "compound
    SMILES", and Ask lists `ord-viewer0102`, `ord-viewer0103`, and `ord-viewer0201`.
  - `test('asks with a pasted compound SMARTS')` and
    `test('asks with a pasted reaction SMARTS')`, each with the reaction IDs that A3
    confirmed.
  - `test('a shared link reproduces the question')`: open the URL from the first test
    in a new page and see the same reactions.
  - `test('the instructions page tries an example')`: from `/ask/help`, Try it on the
    first example reaches `/ask` with the question and its row filled in.

- [ ] **Step 2: Run them**

Run: `npm run test:e2e` in `frontend/apps/viewer`
Expected: PASS

- [ ] **Step 3: Check an R-group drawing by hand.** On the viewer's dev server, use Draw
  structure to draw a benzene carrying an R1 label, and save it. Expected: a row reading
  "compound SMARTS", whose text RDKit reads with `*` at that position. If Indigo writes
  something else, A4's `detect` maps the R-group atoms to `*` before writing, with a stub
  test for that mapping.

- [ ] **Step 4: Raise the coverage floors** to the measured values, rounded down, from
  `npx vitest run --coverage`.

- [ ] **Step 5: Commit, and open the ord-app PR**

```bash
git add frontend/apps/viewer/e2e/ask.spec.ts frontend/apps/viewer/vite.config.ts
git commit -m "Test structures in /ask end to end"
```
