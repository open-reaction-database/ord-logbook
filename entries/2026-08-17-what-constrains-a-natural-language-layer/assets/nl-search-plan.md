# Natural-language search implementation plan

- **Date:** 2026-08-17
- **Author:** Steven Kearnes
- **Status:** draft
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chemist's question becomes a validated `Query`, runs against a `Corpus`, and comes back with the reactions and a sentence about them.

**Architecture:** One forced tool call over the recursive grammar with the ~15K-token prefix cached; the response is coerced (both models return the predicate tree as a JSON string), validated by the existing pydantic models, and compiled. A failure is handed back once with the compiler's own error, which names the bad path and suggests a real one. Execution goes through `Corpus.search`; a second short call sees a summary of the result — never the table — and writes the prose.

**Tech Stack:** Python 3.11+, pydantic 2, `anthropic` SDK, DuckDB via `ord_schema.search.execute`, pytest.

**Spec:** [`nl-search-design.md`](nl-search-design.md), and the measurements it argues from in [the entry](../README.md).

## Global Constraints

- **Model is configuration, never a hard-coded decision.** `DEFAULT_MODEL = "claude-haiku-4-5"`; every entry point takes `model`.
- **The cached prefix must stay byte-stable.** No timestamps, no per-request identifiers, no dict iteration order in the system text or the tool definition. Cache reads are ~90% of the per-query cost.
- **`ord-schema[search]` must remain installable without `anthropic`.** The new dependency goes in an `nl` extra, and `ord_schema/dependencies_test.py` gains a profile row that proves it.
- **Repair runs at most once.** A second failure raises `MalformedQueryError`.
- **No lazy imports.** Every import at module top, per the repository's Python style.
- **Docstrings are Google style**, summary line on one physical line, `Args:`/`Returns:`/`Raises:` where non-empty.
- **Ruff formats at line length 88**; `uv run ruff format` and `uv run ruff check` must pass before every commit.
- **Tests run offline.** Only `nl_eval.py` calls the API, and nothing in the suite invokes it.

---

## File structure

| file | responsibility |
| --- | --- |
| `ord_schema/search/query.py` (modify) | `Reduction`, and the reduction arms of `Order.key` and `Measure.path` |
| `ord_schema/search/nl.py` (create) | errors, client, `translate`, `summarize`, `answer`, `ask` |
| `ord_schema/search/nl_prompt.md` (create) | the system prompt, as prose |
| `ord_schema/search/nl_test.py` (create) | every behavior above, against a stub client |
| `ord_schema/search/nl_eval.py` (create) | `EvalCase`, `load_cases`, `run_case`, `report` |
| `ord_schema/search/nl_cases.yaml` (create) | the eval set |
| `pyproject.toml` (modify) | the `nl` extra |
| `ord_schema/dependencies_test.py` (modify) | the `nl` profile |

---

### Task 1: A reduction over a repeated path

The grammar cannot order by a value under a repeated level, so "the ten highest-yielding reactions" is unwritable. `resolve()` already returns a *list* expression for a repeated path, so a reduction is one DuckDB list aggregate around it.

**Files:**

- Modify: `ord_schema/search/query.py` (`Order`, `Measure`, `compile_query`)
- Test: `ord_schema/search/query_test.py`

**Interfaces:**

- Consumes: `resolve(path, schema=...) -> _Resolved(expression, repeated, dtype)`, `QueryError`.
- Produces: `Reduction` with fields `reduce: Literal["min","max","avg","sum","count"]` and `path: str`; `Order.key: str | Reduction`; `Measure.path: str | Reduction | None`.

- [ ] **Step 1: Write the failing test**

```python
def test_ordering_by_a_reduction_over_a_repeated_path():
    compiled = query.compile_query(
        query.Query.model_validate(
            {
                "order_by": [
                    {
                        "key": {
                            "reduce": "max",
                            "path": "outcomes.products.measurements.percentage.value",
                        },
                        "descending": True,
                    }
                ],
                "limit": 10,
            }
        )
    )
    assert "list_max(" in compiled.sql
    assert compiled.sql.endswith("DESC LIMIT 10")


def test_a_reduction_over_a_scalar_path_is_refused():
    # A scalar needs no reducing, and accepting one would give two spellings for the
    # same query -- one of which silently wraps a value in a single-element list.
    with pytest.raises(query.QueryError, match="already scalar"):
        query.compile_query(
            query.Query.model_validate(
                {
                    "order_by": [
                        {
                            "key": {
                                "reduce": "max",
                                "path": "conditions.temperature.setpoint_kelvin",
                            }
                        }
                    ]
                }
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest ord_schema/search/query_test.py -k reduction -v`
Expected: FAIL — `Order.key` rejects a dict, so pydantic raises a `ValidationError`.

- [ ] **Step 3: Add the model and the compiler support**

In `ord_schema/search/query.py`, above `class Order`:

```python
# DuckDB's list aggregates, which ignore nulls; count is the number of values that are
# actually there, so it filters rather than taking len() of a list holding nulls.
_REDUCERS = {
    "min": "list_min({expression})",
    "max": "list_max({expression})",
    "avg": "list_avg({expression})",
    "sum": "list_sum({expression})",
    "count": "len(list_filter({expression}, value -> value IS NOT NULL))",
}


class Reduction(BaseModel):
    """One value per reaction, reduced from a path that crosses a repeated level.

    An ordering key and an aggregate's argument both have to be scalar, which leaves
    "the highest-yielding reactions" unwritable: a yield lives under outcomes,
    products, and measurements, so the path resolves to a list. This reduces that list
    to the one number the reaction is judged by.

    Attributes:
        reduce: How to reduce the list to a value.
        path: A dotted path that crosses at least one repeated level.
    """

    reduce: Literal["min", "max", "avg", "sum", "count"]
    path: str
```

And the resolver, beside `_scalar`:

```python
def _reduced(reduction: Reduction, schema: pa.Schema) -> str:
    """Returns the expression reducing a repeated path to one value per reaction.

    Args:
        reduction: What to reduce, and how.
        schema: Schema the path is resolved against.

    Returns:
        A DuckDB expression yielding one scalar per reaction, NULL where the reaction
        holds no elements at all.

    Raises:
        QueryError: If the path does not cross a repeated level, since a scalar path
            needs no reduction and accepting one would give a query two spellings.
    """
    resolved = resolve(reduction.path, schema=schema)
    if not resolved.repeated:
        raise QueryError(
            f"{reduction.path}: {reduction.reduce} reduces a repeated level, and this "
            f"path is already scalar; order by the path itself"
        )
    return _REDUCERS[reduction.reduce].format(expression=resolved.expression)
```

Widen the two fields:

```python
class Order(BaseModel):
    """How to sort the result."""

    key: str | Reduction
    descending: bool = False
```

```python
    fn: Literal["count", "count_distinct", "sum", "avg", "min", "max"]
    path: str | Reduction | None = None
    name: str
```

- [ ] **Step 4: Teach `compile_query` both places**

The measure argument, replacing `argument = _scalar(measure.path, schema, measure.fn)`:

```python
            elif isinstance(measure.path, Reduction):
                argument = _reduced(measure.path, schema)
            else:
                argument = _scalar(measure.path, schema, measure.fn)
```

The ordering key, at the top of the `for order in query.order_by:` body:

```python
            if isinstance(order.key, Reduction):
                key = _reduced(order.key, schema)
            elif orderable is None:
```

An aggregated query still orders by a measure name or a `group_by` path; a reduction is a per-reaction value and there is no such row after grouping. Leave that arm as it is — a `Reduction` reaching it is caught by the `isinstance` above only for the ungrouped case, so add the guard:

```python
            if isinstance(order.key, Reduction) and orderable is not None:
                raise QueryError(
                    "an aggregated query orders by a measure name or a group_by path; "
                    "reduce inside a measure instead"
                )
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest ord_schema/search/query_test.py -v`
Expected: PASS, including the two new tests.

- [ ] **Step 6: Check the reduction against real data**

Run:

```bash
uv run python -c "
from ord_schema.search import execute, query
corpus = execute.Corpus('~/ord/projections/**/*.parquet', '~/ord/structures/**/*.parquet',
                        require_current=False, resolver={}.__getitem__)
table = corpus.search(query.Query.model_validate({
    'order_by': [{'key': {'reduce': 'max', 'path': 'outcomes.products.measurements.percentage.value'},
                  'descending': True}],
    'limit': 10}))
print(table.num_rows)
"
```

Expected: 10 rows. This is the question both models tried to write and could not.

- [ ] **Step 7: Document it**

Add a row to the worked-example table in `ord_schema/search/README.md`:

```markdown
| the ten highest-yielding reactions | `order_by` a `reduce` over `outcomes.products.measurements` | no quantifier: a list aggregate over the projection |
```

- [ ] **Step 8: Commit**

```bash
git add ord_schema/search/query.py ord_schema/search/query_test.py ord_schema/search/README.md
git commit -m "Let a query order by a value under a repeated level"
```

---

### Task 2: The package, its dependency, and its errors

**Files:**

- Create: `ord_schema/search/nl.py`, `ord_schema/search/nl_test.py`
- Modify: `pyproject.toml`, `ord_schema/dependencies_test.py`

**Interfaces:**

- Produces: `NLQueryError`, `ModelUnavailableError`, `ModelRateLimitedError`, `MalformedQueryError`, `DEFAULT_MODEL = "claude-haiku-4-5"`, `get_client() -> anthropic.Anthropic`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_errors_share_one_base():
    # ord-interface maps these onto status codes, so a caller can catch the base and
    # still tell a rate limit from a query it could not build.
    assert issubclass(nl.ModelRateLimitedError, nl.NLQueryError)
    assert issubclass(nl.ModelUnavailableError, nl.NLQueryError)
    assert issubclass(nl.MalformedQueryError, nl.NLQueryError)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest ord_schema/search/nl_test.py -v`
Expected: FAIL — `ModuleNotFoundError: ord_schema.search.nl`.

- [ ] **Step 3: Write the module head**

```python
"""Natural-language questions, translated into the search grammar and answered.

A model cannot be constrained to emit a valid Query: the grammar is recursive, and both
constrained-decoding paths refuse it -- the measurements are in the ord-logbook entry
"What constrains a natural-language layer over the search grammar". So translation is
generation checked afterwards: the response is coerced, validated by the same models the
compiler uses, and handed back once with the compiler's error when it does not compile.
"""

import dataclasses
import json
from importlib import resources
from typing import Any

import anthropic
import pyarrow as pa

from ord_schema.logging import get_logger
from ord_schema.search import execute, query, schema

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 2048


class NLQueryError(Exception):
    """A question could not be answered."""


class ModelUnavailableError(NLQueryError):
    """The model could not be reached."""


class ModelRateLimitedError(NLQueryError):
    """The model refused the request for rate reasons."""


class MalformedQueryError(NLQueryError):
    """The model's query did not validate, and the repair attempt did not either."""


def get_client() -> anthropic.Anthropic:
    """Returns a client reading its credentials from the environment."""
    return anthropic.Anthropic()
```

- [ ] **Step 4: Run it**

Run: `uv run pytest ord_schema/search/nl_test.py -v`
Expected: PASS.

- [ ] **Step 5: Declare the dependency**

In `pyproject.toml`, after the `search` extra:

```toml
# Optional: ord_schema.search.nl turns a question into a Query by asking a model, so it
# needs an API client where the rest of the search subpackage needs none.
nl = [
    "anthropic>=0.120",
    "ord-schema[search]",
]
```

In `ord_schema/dependencies_test.py`, add to both dictionaries:

```python
    "nl": ("ord_schema.search.nl",),
```

```python
    "nl": ("search", "nl"),
```

- [ ] **Step 6: Run the dependency test**

Run: `uv run pytest ord_schema/dependencies_test.py -v`
Expected: PASS — five profiles, none skipped, since `anthropic` is installed in a development checkout.

- [ ] **Step 7: Commit**

```bash
git add ord_schema/search/nl.py ord_schema/search/nl_test.py pyproject.toml ord_schema/dependencies_test.py
git commit -m "Add the natural-language module, its extra, and its errors"
```

---

### Task 3: Translation, with the coercing parse

**Files:**

- Create: `ord_schema/search/nl_prompt.md`
- Modify: `ord_schema/search/nl.py`, `ord_schema/search/nl_test.py`

**Interfaces:**

- Consumes: `schema.describe()`, `query.Query`, `query.compile_query`, the errors from Task 2.
- Produces: `translate(question, *, client=None, model=DEFAULT_MODEL, repair=True) -> query.Query`; `SYSTEM_PROMPT: str`; `TOOL: dict`.

- [ ] **Step 1: Write the failing tests**

```python
class _StubClient:
    """Returns canned tool calls, and records what it was asked."""

    def __init__(self, *inputs):
        self._inputs = list(inputs)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        payload = self._inputs.pop(0)
        block = types.SimpleNamespace(
            type="tool_use", id="toolu_stub", name="build_query", input=payload
        )
        usage = types.SimpleNamespace(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return types.SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use")


_WHERE = {
    "op": "exists",
    "path": "inputs.components",
    "where": {"op": "eq", "path": "reaction_role", "value": {"literal": "SOLVENT"}},
}


def test_a_tree_returned_as_a_json_string_is_still_understood():
    # Both models do this, most of the time: the predicate arrives JSON-encoded inside
    # a string rather than as an object.
    client = _StubClient({"where": json.dumps(_WHERE)})
    result = nl.translate("solvent reactions", client=client)
    assert result.where.op == "exists"


def test_the_prefix_is_marked_cacheable():
    # Cache reads are most of what a query costs; an uncached prefix is a 10x bill.
    client = _StubClient({"where": _WHERE})
    nl.translate("solvent reactions", client=client)
    system = client.requests[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_the_schema_reaches_the_prompt():
    client = _StubClient({"where": _WHERE})
    nl.translate("solvent reactions", client=client)
    assert "reaction_role" in client.requests[0]["system"][0]["text"]
```

- [ ] **Step 2: Run them**

Run: `uv run pytest ord_schema/search/nl_test.py -v`
Expected: FAIL — `AttributeError: module 'ord_schema.search.nl' has no attribute 'translate'`.

- [ ] **Step 3: Write the prompt**

`ord_schema/search/nl_prompt.md`:

```markdown
You turn a chemist's question into one ORD search query by calling `build_query`.

Rules that keep a query answerable:

- Paths are dotted names from the schema below. There is no array syntax: write
  `inputs.components`, never `inputs[].components` or `identifiers[*].value`.
- Any path that crosses a repeated level must be bound by `exists` or `forall`, and the
  paths inside that quantifier are relative to the bound element.
- Two conditions on the *same* element go inside one quantifier. Two conditions on
  *different* elements are two quantifiers.
- Name compounds rather than spelling structures: `{"compound": "pyridine"}` resolves to
  SMILES. Use `substructure` with a SMARTS only for a pattern the user describes.
- To rank by a value under a repeated level, order by a reduction:
  `{"reduce": "max", "path": "outcomes.products.measurements.percentage.value"}`.
- Prefer the smallest query that answers the question, and set `limit` when the user
  asks for a number of results.

The corpus schema, as an indented type tree in DuckDB's types:
```

- [ ] **Step 4: Implement translation**

```python
SYSTEM_PROMPT = (
    (resources.files("ord_schema.search") / "nl_prompt.md").read_text(encoding="utf-8")
    + "\n\n"
    + schema.describe()
)

# Built once: the tool definition is part of the cached prefix, so a dict rebuilt per
# call with a different key order would silently cost a cache miss.
TOOL: dict[str, Any] = {
    "name": "build_query",
    "description": "Build an ORD search query from the user's question.",
    "input_schema": query.Query.model_json_schema(),
}
_SYSTEM = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
]


def _coerce(value: Any) -> Any:
    """Returns the value with JSON-encoded strings parsed back into objects.

    A model handed a recursive tool schema usually returns the nested predicate as a
    JSON string rather than an object, which pydantic rejects. Parsing it back is the
    normal path rather than a fallback.
    """
    if isinstance(value, str):
        try:
            return _coerce(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value
    if isinstance(value, dict):
        return {key: _coerce(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_coerce(item) for item in value]
    return value


def _ask_model(client, model, messages):
    """Returns the tool_use block from one forced call, mapping API failures."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            messages=messages,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "build_query"},
        )
    except anthropic.RateLimitError as error:
        raise ModelRateLimitedError(str(error)) from error
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
        raise ModelUnavailableError(str(error)) from error
    for block in response.content:
        if block.type == "tool_use":
            return block
    raise MalformedQueryError("the model returned no query")
```

- [ ] **Step 5: Add `translate` itself**

```python
def translate(
    question: str,
    *,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    repair: bool = True,
) -> query.Query:
    """Returns the query a question asks for.

    Args:
        question: The question, in English.
        client: Anthropic client; one is built from the environment if omitted.
        model: Which model translates. Cheap models need the repair turn more often.
        repair: Hand a failure back once with the compiler's error. Off for measuring
            first-try accuracy.

    Returns:
        A Query that compiles against the projection schema.

    Raises:
        MalformedQueryError: If the query does not validate or compile, after the
            repair turn if one was allowed.
        ModelRateLimitedError: If the model is rate limited.
        ModelUnavailableError: If the model cannot be reached.
    """
    client = client if client is not None else get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    block = _ask_model(client, model, messages)
    try:
        return _validated(block.input)
    except (ValueError, query.QueryError) as error:
        if not repair:
            raise MalformedQueryError(str(error)) from error
        first = error
    logger.info("repairing a query that did not compile: %s", first)
    messages += [
        {"role": "assistant", "content": [{"type": "tool_use", "id": block.id,
                                           "name": block.name, "input": block.input}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id,
                                      "is_error": True,
                                      "content": f"That query was rejected: {first}. "
                                                 "Call build_query again with it fixed."}]},
    ]
    retry = _ask_model(client, model, messages)
    try:
        return _validated(retry.input)
    except (ValueError, query.QueryError) as error:
        raise MalformedQueryError(str(error)) from error


def _validated(raw: Any) -> query.Query:
    """Returns the Query a tool call carries, proven to compile."""
    parsed = query.Query.model_validate(_coerce(raw))
    query.compile_query(parsed)
    return parsed
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest ord_schema/search/nl_test.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ord_schema/search/nl.py ord_schema/search/nl_prompt.md ord_schema/search/nl_test.py
git commit -m "Translate a question into a query, coercing what the model returns"
```

---

### Task 4: The repair turn, pinned

**Files:**

- Modify: `ord_schema/search/nl_test.py`

**Interfaces:**

- Consumes: `translate`, `_StubClient` from Task 3.

- [ ] **Step 1: Write the failing tests**

```python
_BAD_PATH = {"op": "eq", "path": "identifiers[*].value", "value": {"literal": "x"}}


def test_a_bad_path_is_handed_back_once_and_recovered():
    client = _StubClient({"where": _BAD_PATH}, {"where": _WHERE})
    result = nl.translate("aspirin reactions", client=client)
    assert result.where.op == "exists"
    assert len(client.requests) == 2


def test_the_repair_carries_the_compiler_s_suggestion():
    client = _StubClient({"where": _BAD_PATH}, {"where": _WHERE})
    nl.translate("aspirin reactions", client=client)
    sent = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "did you mean" in sent


def test_a_second_failure_raises_rather_than_looping():
    client = _StubClient({"where": _BAD_PATH}, {"where": _BAD_PATH})
    with pytest.raises(nl.MalformedQueryError, match="identifiers"):
        nl.translate("aspirin reactions", client=client)
    assert len(client.requests) == 2


def test_repair_can_be_turned_off_for_measurement():
    client = _StubClient({"where": _BAD_PATH})
    with pytest.raises(nl.MalformedQueryError):
        nl.translate("aspirin reactions", client=client, repair=False)
    assert len(client.requests) == 1
```

- [ ] **Step 2: Run them**

Run: `uv run pytest ord_schema/search/nl_test.py -k repair -v`
Expected: PASS if Task 3 was implemented as written; a failure here means the repair path is wrong, not that the test is.

- [ ] **Step 3: Commit**

```bash
git add ord_schema/search/nl_test.py
git commit -m "Pin the repair turn to exactly one attempt"
```

---

### Task 5: The summary and the prose answer

**Files:**

- Modify: `ord_schema/search/nl.py`, `ord_schema/search/nl_test.py`

**Interfaces:**

- Produces: `summarize(table, *, rows=5) -> str`; `answer(question, table, *, client=None, model=DEFAULT_MODEL) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_summary_is_bounded_by_the_row_cap_not_the_table():
    small = pa.table({"reaction_id": ["a", "b"]})
    large = pa.table({"reaction_id": [str(i) for i in range(100_000)]})
    assert len(nl.summarize(large)) < 2 * len(nl.summarize(small))


def test_the_summary_states_the_row_count():
    assert "100000 rows" in nl.summarize(pa.table({"reaction_id": [str(i) for i in range(100_000)]}))
```

- [ ] **Step 2: Run them**

Run: `uv run pytest ord_schema/search/nl_test.py -k summary -v`
Expected: FAIL — `summarize` does not exist.

- [ ] **Step 3: Implement both**

```python
def summarize(table: pa.Table, *, rows: int = 5) -> str:
    """Returns a description of a result small enough to put in a prompt.

    Args:
        table: What the search returned.
        rows: How many sample rows to show.

    Returns:
        The row count, the column names, and up to ``rows`` rows. A result of a hundred
        thousand reactions costs the same prompt as one of three.
    """
    sample = table.slice(0, rows).to_pylist()
    lines = [f"{table.num_rows} rows, columns: {', '.join(table.column_names)}"]
    lines += [json.dumps(row, default=str) for row in sample]
    if table.num_rows > rows:
        lines.append(f"... {table.num_rows - rows} more rows not shown")
    return "\n".join(lines)


def answer(
    question: str,
    table: pa.Table,
    *,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Returns a sentence or two saying what the result shows.

    Args:
        question: The question the result answers.
        table: What the search returned.
        client: Anthropic client; one is built from the environment if omitted.
        model: Which model writes the prose.

    Returns:
        Plain text, with no markdown and no invented chemistry: the model sees a summary
        rather than the rows, so it can only describe what the summary states.

    Raises:
        ModelRateLimitedError: If the model is rate limited.
        ModelUnavailableError: If the model cannot be reached.
    """
    client = client if client is not None else get_client()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=(
                "You describe the result of a database query in one or two plain "
                "sentences. State only what the summary shows. Do not invent "
                "chemistry, and do not use markdown."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nResult:\n{summarize(table)}",
                }
            ],
        )
    except anthropic.RateLimitError as error:
        raise ModelRateLimitedError(str(error)) from error
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
        raise ModelUnavailableError(str(error)) from error
    return "".join(block.text for block in response.content if block.type == "text")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest ord_schema/search/nl_test.py -k summary -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ord_schema/search/nl.py ord_schema/search/nl_test.py
git commit -m "Summarize a result and let the model describe it"
```

---

### Task 6: The round trip

**Files:**

- Modify: `ord_schema/search/nl.py`, `ord_schema/search/nl_test.py`

**Interfaces:**

- Produces: `Answer(question, query, table, text)`; `ask(question, corpus, *, client=None, model=DEFAULT_MODEL, timeout_seconds=60.0) -> Answer`.

- [ ] **Step 1: Write the failing test**

```python
def test_ask_returns_the_query_it_ran(corpus):
    # The caller needs the query to show what was actually asked, and to offer a rerun.
    client = _StubClient({"where": _WHERE}, _text("Two reactions, both with pyridine."))
    result = nl.ask("solvent reactions", corpus, client=client)
    assert result.query.where.op == "exists"
    assert result.table.num_rows == result.table.num_rows
    assert "pyridine" in result.text
```

Extend `_StubClient` so a canned entry that is a string becomes a text response:

```python
def _text(value: str):
    return value


# in _StubClient.create, before building the tool_use block:
        if isinstance(payload, str):
            block = types.SimpleNamespace(type="text", text=payload)
            return types.SimpleNamespace(content=[block], usage=usage, stop_reason="end_turn")
```

- [ ] **Step 2: Run it**

Run: `uv run pytest ord_schema/search/nl_test.py -k ask -v`
Expected: FAIL — `ask` does not exist.

- [ ] **Step 3: Implement it**

```python
@dataclasses.dataclass(frozen=True)
class Answer:
    """What a question produced, including the query it became.

    Attributes:
        question: The question as asked.
        query: The query that ran, for display and for running again.
        table: What the search returned.
        text: A sentence or two describing the result.
    """

    question: str
    query: query.Query
    table: pa.Table
    text: str


def ask(
    question: str,
    corpus: execute.Corpus,
    *,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 60.0,
) -> Answer:
    """Answers a question against a corpus.

    Args:
        question: The question, in English.
        corpus: The corpus to search.
        client: Anthropic client; one is built from the environment if omitted.
        model: Which model translates and describes.
        timeout_seconds: Passed to the search, so a slow query fails rather than hangs.

    Returns:
        The query, the reactions, and a description of them.

    Raises:
        MalformedQueryError: If translation does not produce a query that compiles.
        ModelRateLimitedError: If the model is rate limited.
        ModelUnavailableError: If the model cannot be reached.
    """
    client = client if client is not None else get_client()
    translated = translate(question, client=client, model=model)
    table = corpus.search(translated, timeout_seconds=timeout_seconds)
    return Answer(
        question=question,
        query=translated,
        table=table,
        text=answer(question, table, client=client, model=model),
    )
```

- [ ] **Step 4: Run the whole file**

Run: `uv run pytest ord_schema/search/nl_test.py -v`
Expected: PASS, and no test makes a network call.

- [ ] **Step 5: Document it**

Add to `ord_schema/search/README.md`, under `## Usage`:

````markdown
### Ask in English

```python
from ord_schema.search import execute, nl

corpus = execute.Corpus("projections/*/*.parquet", "structures/*/*.parquet")
answer = nl.ask("which reactions use pyridine as a solvent?", corpus)
print(answer.query, answer.table.num_rows, answer.text)
```

Needs the `nl` extra (`pip install "ord-schema[nl]"`) and `ANTHROPIC_API_KEY`. The model
cannot be constrained to emit a valid query — the grammar is recursive and both
constrained-decoding paths refuse it — so a failure is handed back once with the
compiler's own error, and a second failure raises `MalformedQueryError`.
````

- [ ] **Step 6: Commit**

```bash
git add ord_schema/search/nl.py ord_schema/search/nl_test.py ord_schema/search/README.md
git commit -m "Answer a question end to end"
```

---

### Task 7: The eval harness

**Files:**

- Create: `ord_schema/search/nl_eval.py`, `ord_schema/search/nl_cases.yaml`, `ord_schema/search/nl_eval_test.py`

**Interfaces:**

- Consumes: `translate`, `execute.Corpus`.
- Produces: `EvalCase`, `load_cases(path) -> list[EvalCase]`, `run_case(case, corpus, *, client, model, repair) -> CaseResult`, `report(results) -> str`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_case_that_returns_a_forbidden_reaction_fails(corpus):
    # Scoring on reactions rather than on query shape is what lets the harness say a
    # translation is wrong rather than merely differently spelled.
    case = nl_eval.EvalCase(
        question="solvent reactions",
        must_return=["ord-aa000000000000000000000000000000"],
        must_not_return=["ord-bb000000000000000000000000000000"],
    )
    result = nl_eval.score(case, returned=["ord-bb000000000000000000000000000000"])
    assert not result.passed
    assert "must_not_return" in result.detail
```

- [ ] **Step 2: Run it**

Run: `uv run pytest ord_schema/search/nl_eval_test.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the harness**

```python
class EvalCase(BaseModel):
    """One question and what any correct answer to it must satisfy.

    Attributes:
        question: The question, in English.
        must_return: Reaction IDs any correct query returns.
        must_not_return: Reaction IDs a near-miss would wrongly include.
        compiles: Whether the question should translate at all; False marks a question
            the grammar cannot express, which the layer must refuse rather than fudge.
    """

    question: str
    must_return: list[str] = Field(default_factory=list)
    must_not_return: list[str] = Field(default_factory=list)
    compiles: bool = True


@dataclasses.dataclass(frozen=True)
class CaseResult:
    """How one case came out."""

    case: EvalCase
    passed: bool
    detail: str


def score(case: EvalCase, returned: Sequence[str]) -> CaseResult:
    """Returns whether the reactions a query returned satisfy the case."""
    found = set(returned)
    missing = [value for value in case.must_return if value not in found]
    forbidden = [value for value in case.must_not_return if value in found]
    if missing:
        return CaseResult(case, False, f"must_return absent: {missing}")
    if forbidden:
        return CaseResult(case, False, f"must_not_return present: {forbidden}")
    return CaseResult(case, True, f"{len(found)} reactions")


def load_cases(path: str) -> list[EvalCase]:
    """Returns the cases a YAML file holds."""
    with pathlib.Path(path).open(encoding="utf-8") as handle:
        return [EvalCase.model_validate(entry) for entry in yaml.safe_load(handle)]
```

- [ ] **Step 4: Add the runner and the report**

```python
def run_case(
    case: EvalCase,
    corpus: execute.Corpus,
    *,
    client: anthropic.Anthropic,
    model: str,
    repair: bool,
) -> CaseResult:
    """Translates and runs one case, returning how it scored."""
    try:
        translated = nl.translate(case.question, client=client, model=model, repair=repair)
    except nl.MalformedQueryError as error:
        passed = not case.compiles
        return CaseResult(case, passed, f"did not compile: {error}")
    if not case.compiles:
        return CaseResult(case, False, "compiled, but the case expects it cannot")
    table = corpus.search(translated)
    return score(case, table.column("reaction_id").to_pylist())


def report(results: Sequence[CaseResult]) -> str:
    """Returns a human-readable summary, failures first."""
    passed = sum(result.passed for result in results)
    lines = [f"{passed}/{len(results)} passed"]
    lines += [
        f"  FAIL {result.case.question}: {result.detail}"
        for result in results
        if not result.passed
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Write the starting cases**

`ord_schema/search/nl_cases.yaml`, with reaction IDs filled in by running each query by hand against the local corpus first:

```yaml
# Each case states what any correct translation must return, never a Query literal:
# several spellings are right, and pinning one would fail a better query than the one
# that was written when the case was added.
- question: reactions using pyridine as the solvent
  must_return: []
  must_not_return: []
- question: reactions run above 350 K
  must_return: []
  must_not_return: []
- question: the ten highest-yielding reactions
  must_return: []
  must_not_return: []
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest ord_schema/search/nl_eval_test.py -v`
Expected: PASS.

- [ ] **Step 7: Take the first real measurement**

Run, with a key in the environment and the local corpus:

```bash
uv run python -m ord_schema.search.nl_eval --model claude-haiku-4-5 --repair
uv run python -m ord_schema.search.nl_eval --model claude-opus-5 --repair
```

Record both in the logbook entry rather than in a commit message: the numbers in
finding 6 came from ten ad-hoc questions and want replacing with these.

- [ ] **Step 8: Commit**

```bash
git add ord_schema/search/nl_eval.py ord_schema/search/nl_cases.yaml ord_schema/search/nl_eval_test.py
git commit -m "Score translations on the reactions they return"
```

---

## Self-review

**Spec coverage.** `ask`/`translate`/`answer` — Tasks 3, 5, 6. Cached prefix — Task 3, pinned by a test. Coercion — Task 3. One repair turn — Tasks 3 and 4. Summary not table — Task 5. Module layout and the `nl` extra — Task 2. Error taxonomy — Task 2. Eval harness scoring on reactions — Task 7. The reduction gap — Task 1. Out of scope in the spec and absent here: multi-turn, a second backend, constrained decoding, text-search tuning.

**Types.** `translate` returns `query.Query` in Tasks 3, 6, and 7. `Answer.query` is that same type. `summarize` and `answer` both take `pa.Table`, which is what `Corpus.search` returns. `Reduction` is referenced by `Order.key` and `Measure.path` only.

**Known gaps, deliberately left to the executor.** The eval cases in Task 7 ship with empty `must_return` lists, because the IDs have to come from running each query against the local corpus — filling them in is step 5's work, and inventing IDs here would be worse than leaving them empty. Task 1's step 6 needs the local projections; it is a check, not a test, and does not run in CI.
