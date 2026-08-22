# Where the question log lives

- **Date:** 2026-08-22
- **Author:** Steven Kearnes
- **Status:** draft (nothing here is implemented)
- **Tags:** ord-schema, search, natural-language, observability, evals, aws, s3, duckdb
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`ord_schema.search.nl` answers a question and keeps nothing. The `/nl_query` endpoint
ord-interface serves today keeps a little less than nothing that lasts: one `logger.info`
line per request, into CloudWatch Logs, aged out on the log group's retention.

The questions people actually ask are the only material that can refine a translator --
the prompt, the grammar, and the eval set are all guesses until real questions land
against them -- and they are being discarded as fast as they arrive. So: where does a
durable record of every question and the query it became live, and what is in it?

## Summary

**An append-only event log of JSON objects in S3**, read with DuckDB. Three event kinds
share a `record_id`: the **ask**, written by the library; the **thumb**, from an anonymous
visitor; the **label**, from a maintainer. Results are not stored -- the translation and a
corpus fingerprint reproduce them on demand.

It goes in **a new private bucket, not the `open-reaction-database` one**. That bucket
holds artifacts meant to be publishable, and the log is the opposite: free text people
typed, against session identifiers. Keeping them apart is not about today's permissions
-- account-level Block Public Access covers both -- but about what it costs to open the
public bucket later. Separate buckets make that a policy change; one bucket makes it an
audit of every prefix, forever, and an audit that has to be right every time.

Operational signals stay in CloudWatch. The log is for refinement; a store asked to be
both a refinement corpus and a monitoring surface is read as neither, and error rate,
latency, and token cost are metrics rather than records.

Three constraints decided it, and only the first is about storage:

1. **There is no service to write from.** `search.nl` is a library; its callers today are
   the eval harness and a terminal. An S3 sink records those from a laptop with nothing
   but AWS credentials. A Postgres sink needs an SSM port-forward through the bastion
   before a local eval run can log anything at all -- which means, in practice, that
   local runs would go unrecorded, and those are the runs happening now.
2. **The corpus lives in a database that is replaced.** The cluster carries `app`, `ord`,
   `ord_20260702`, and `editor`; the dated one is rebuilt and cut over. A log beside the
   corpus dies at the next rebuild. The persistent databases would serve, but the cluster
   is a `db.t4g.large` sized for structure search's buffer cache and shared with
   production: one insert per question is nothing, and a year-wide analytic scan for eval
   mining is not.
3. **Feedback is not a column.** A thumb from a visitor, a maintainer's verdict, and a
   promotion into the eval set are three assertions, by three parties, at three times.
   Folding them onto one mutable row loses who said what and when, which is precisely
   what you want on the day a label contradicts a thumb.

## Method

This is mostly a design record rather than a measurement. The storage decision argues
from constraints already true of the deployed system, each read out of the stacks or the
code rather than assumed:

| Claim | Where it was verified |
| --- | --- |
| The live NL endpoint's whole record is one stdout line | `ord_interface/api/nl_query.py` on ord-interface `origin/main` |
| `search.nl` records nothing, and discards `response.usage` | [`ord_schema/search/nl.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/nl.py) |
| `Corpus` exposes no version or fingerprint | [`ord_schema/search/execute.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/execute.py) -- stamps are read at construction and indexed by `source_md5`, never surfaced |
| The only bucket the stack provisions is the publishable one | `stacks/backend/__main__.py`, `aws.s3.Bucket("ord_bucket", bucket="open-reaction-database")` -- so the log needs a new one |
| Block Public Access is set account-wide | `stacks/account/`, per the repository README |
| The dated corpus database is one of four on a shared cluster | `stacks/database/README.md` |
| The cluster is a 2-vCPU `db.t4g.large` chosen for RAM | `stacks/backend/README.md`, "Database sizing" |

One question could not be settled by reading anything, because it is about how DuckDB
behaves rather than about how the system is built: whether a log whose payload is a
model-authored query survives compaction into Parquet. That one is measured, by
[`assets/parquet-compaction-probe.py`](assets/parquet-compaction-probe.py), and the
answer changed the record shape.

The one number still *not* verified is volume, and it matters only for deciding when to
compact; see [Conclusions](#conclusions--next-steps).

## Findings

### The record

Three event kinds, one JSON object each, all carrying `record_id`. Only the ask is
written by the library.

```json
{
  "event": "ask",
  "record_id": "0f3c…",          "session_id": "a91b…",   "timestamp": "2026-08-22T18:04:11Z",
  "question": "which reactions use pyridine as a solvent?",
  "attempts": [
    {"translation": "{\"op\":\"exists\",\"path\":\"conditions.solvent\",…}",
     "error": "no such path: conditions.solvent; did you mean inputs.components.reaction_role?",
     "usage": {"input": 412, "output": 233, "cache_read": 15104, "cache_creation": 0}},
    {"translation": "{\"op\":\"exists\",\"path\":\"inputs.components\",…}",
     "error": null,
     "usage": {"input": 689, "output": 241, "cache_read": 15104, "cache_creation": 0}}
  ],
  "outcome": "empty",
  "row_count": 0,
  "declined_reason": null,
  "error": null,
  "answer_text": "No reactions matched.",
  "model": "claude-haiku-4-5",
  "prompt_fingerprint": "7d1a4c9e2f08",
  "corpus_fingerprint": "b42f19ac",
  "ord_schema_version": "0.3.86",
  "usage": {"input": 412, "output": 233, "cache_read": 15104, "cache_creation": 0},
  "timings_ms": {"translate": 1840, "search": 212, "answer": 640}
}
```

The thumb is `{event, record_id, session_id, timestamp, value: up|down, comment}`. The
label is `{event, record_id, timestamp, verdict: correct|wrong|unclear, reference, note,
promoted}`.

A translation is stored as a **JSON string**, not as a nested object, for reasons
measured in [the next section](#the-payload-is-a-string-because-a-struct-loses-fields).
Everything around it is typed.

`usage` and `timings_ms` at the top level are the totals for the whole ask -- what the
question actually cost -- and the reader derives the rest from `attempts` rather than
storing it: the `translation` is the last attempt whose `error` is null (and null if none
is), `repaired` is `len(attempts) > 1`, and a model that declined only after the compiler
refused a guess is `outcome = 'declined'` with a non-empty list.

Nothing identifying is stored beyond a session identifier the client mints: no IP
address, no user agent, no account. Questions are free text a person typed, which is
reason enough for the design to state a retention period rather than let one accrete by
default.

### The payload is a string, because a struct loses fields

The record's payload is a `Query` the model wrote: recursive, differently shaped record
to record, and -- on the attempt that matters most -- not even valid. Storing it as a
nested object and compacting a month into Parquet means letting DuckDB infer a struct
type from whichever shapes that month happened to hold. The probe asked what that costs.

Compaction itself is fine, which is not what I expected: two months whose inferred types
genuinely differ (`STRUCT(op, path, value, clauses)` against `STRUCT(op, path, where)`)
compacted and read back together, all rows present. The damage is one level down.

| Read across two compacted months | Nested | JSON string |
| --- | --- | --- |
| `count(*)` | 3 rows | 3 rows |
| a field the *first* month's type has | returns it | returns it |
| a field only the *second* month's type has | `Binder Error: Could not find key "where" in struct` | returns it |
| the same, with `union_by_name=true` | `Conversion Error` reading the file | n/a |
| a shape first appearing past the inference sample | `Binder Error: Could not find key "threshold"` | returns it |

The second row is the bad one, and it is bad in the quiet way. The unified read takes the
first file's struct, so the later month's record still *counts* -- it is there in
`count(*)`, it is there in every aggregate -- while the part of it that made it worth
recording is unreachable. A query for `similarity` predicates over a year would return a
confident, wrong, low number. `union_by_name=true`, the documented fix for exactly this,
refuses the mismatched structs outright, which is at least loud.

The last row is the same failure with a longer fuse. `read_json_auto` infers from a
sample -- 20,480 rows by default -- so a predicate form that stays rare until the log is
large is simply not in the schema, and querying it errors rather than returning nothing.
The probe reproduces this with `sample_size=10` and a shape at record 50.

As a JSON string every one of these reads correctly and identically: DuckDB types the
column `JSON`, `->` returns the value where it exists and NULL where it does not, and no
inference happens at all. The cost is `->'$.op'` instead of `.op`, and losing the ability
to have the compiler check a path that was never checkable anyway -- these are strings a
model wrote.

So the record is a **typed envelope around an opaque payload**: identifiers, outcome,
usage, timings, and fingerprints are columns; question, translation, and error text are
strings. That is also the honest correction to a glib line in the first draft of this
entry -- "half of what it records is off-schema" is not an argument against a table,
since `jsonb` would hold it perfectly well. It is an argument against typing the payload,
in whichever store.

### The outcome field labels a good share of the corpus for free

`outcome` is one of `answered`, `empty`, `declined`, `malformed`, `rate_limited`,
`unavailable`, `unresolved_compound`, `timeout`, or `search_failed` -- the error taxonomy
`nl.py` already raises, plus the split between a query that returned rows and one that
returned none.

Three of those are failures that need no human to recognize them. A question that
translated and returned **zero rows** is either a real gap in the corpus or a wrong
translation, and it is nearly always worth reading. A question that reached
`MalformedQueryError` failed the compiler twice, with the compiler's own suggestion in
hand. A question the model **declined** is a claim that the grammar cannot express it,
which is either true -- and worth knowing how often -- or a translator giving up on
something it should have written.

`UnanswerableError` already carries an `attempted` flag, for a distinction worth keeping:
declining after the compiler refused a guess is a different event from reading the
question and saying no, and only the second is the behavior the layer is trying to have.
Against an attempts list that flag stops being a field at all -- the model that declined
outright has an empty list, and the one that built a query first does not.

The session identifier is what turns isolated pairs into something you can learn from.
Grouped by session, the log shows the reformulation chain -- *asked X, got nothing,
rephrased to Y, rephrased to Z, stopped* -- and the user's own next attempt is a free
approximate label on the previous failure. That signal cannot be reconstructed later from
unlinked records, which is the argument for minting the identifier before there is any
service to use it.

### A repair is not a second question

Two things look alike -- a query that follows a failed one -- and they want opposite
treatments. The **repair turn** is internal to one `translate()` call: same question, same
conversation, two assistant turns, and the caller never sees the first attempt. It is one
record. A **rephrasing** is a new question with its own record, linked to the previous one
by session and timestamp order, and nothing more is needed to reconstruct the chain.

So repair is recorded inside the record, as the attempts themselves rather than as a
boolean. That costs a nested list and buys two things the boolean cannot:

- **The rejected query and the error that rejected it.** Which paths does the model invent
  that the schema does not have? Which of the compiler's suggestions does the second turn
  actually take? Prompt work runs on exactly this, and `repaired: true` discards all of
  it.
- **What repair costs.** The case for the cheap model is Haiku plus one repair turn at
  5.6× lower cost than Opus, measured [in the entry that settled the
  design](../2026-08-17-what-constrains-a-natural-language-layer/README.md). How often
  the second turn rescues a query, and what it costs when it does, is the open question
  about that choice -- and per-attempt usage answers it directly, with no separate
  experiment.

An explicit parent pointer would earn its place for one thing only, and that thing does
not exist yet: a feature offering "edit this query and run it again" would make a new ask
derive from one specific prior record, which session and timestamp cannot express. A
`derived_from` field belongs in the record on the day that ships, not before.

### Two fingerprints, and what each is for

**`prompt_fingerprint`** hashes the system prompt and both tool definitions. It answers
"which translator wrote this" when comparing a March record against today's behavior, and
it doubles as a standing check on something `nl.py`'s own docstring insists on: the
cached prefix must stay byte-stable, because cache reads are most of what a query costs.
The fingerprint changes exactly when the cache would miss. A run where it moves
unexpectedly is money already spent.

**`corpus_fingerprint`** hashes the paired `source_md5` stamps. Because results are not
stored, this is the whole reproducibility story: the translation plus the corpus it ran
against regenerate the rows whenever they are wanted. It also keeps an old record honest
-- a query that returned nothing against a corpus from May is not evidence about the
corpus today.

This one does not exist yet. `Corpus` reads the stamps at construction and indexes pairs
by `source_md5` without exposing either, so a small public accessor is part of the work.

### What has to change in `nl.py`

`translate()` returns a `Query` and drops everything else on the floor -- the usage block,
the timings, whether the repair turn fired. Nothing here is deployed, so the return type
changes rather than growing an out-parameter beside it:

```python
@dataclasses.dataclass(frozen=True)
class Attempt:
    translation: dict[str, Any]   # the coerced tool input, which need not be valid
    error: str | None
    usage: Usage

@dataclasses.dataclass(frozen=True)
class Translation:
    query: query.Query
    attempts: tuple[Attempt, ...]
    elapsed_ms: float

def translate(question, ...) -> Translation
def ask(question, corpus, *, session_id=None, sink=None, ...) -> Answer
```

An attempt holds the raw tool input rather than a `Query`, because the attempt worth
recording is usually the one that *failed* `model_validate` -- there is no `Query` object
to hold. In memory it stays a dict; the sink serializes it to a JSON string on the way
out, for the reason the probe found.

The failure paths are what make the new return type the better shape rather than merely
the tidier one. A record is most interesting exactly when translation didn't work, and a
malformed query that burned two turns has spent real money -- but an exception carries no
return value, so an accumulator was the only way to get that back out. Instead
`NLQueryError` grows `attempts` and `elapsed_ms`, and every path reports what it cost and
what it tried, whether it ended in a query, a refusal, or a compiler error.

`Answer` grows a `record_id` for the same reason: whatever serves this has to hand the
identifier to the browser, or there is nothing for a thumb to reference.

The sink is a one-method protocol with four implementations -- `NullSink` (the default),
`JsonlSink` for tests and local runs, `S3Sink` behind its own extra so
`ord-schema[search]` stays free of boto3, and `StdoutSink` for a container whose logs
already go somewhere. Every write is **best-effort**: a sink failure warns and never fails
the query, which is the discipline the codebase already applies to the Redis translation
cache -- an optimization, never a dependency.

The eval harness gets something it cannot currently measure at all: `run_case` already
calls `translate`, so per-case token cost and translate latency arrive with the new return
type. That is the missing half of any "is the cheap model worth it" comparison, which
until now could compare only pass rates.

### Why not a table, and why not CloudWatch

A table in the persistent `app` or `ord` database is the obvious alternative, and it wins
on two counts: a point update is the natural shape for a thumb, and SQL is a good review
surface. It loses on the case that exists today -- every local eval run would need the
bastion tunnel -- and the SQL advantage is smaller than it looks, because DuckDB reading
the objects *is* SQL, over the same query engine the rest of `ord_schema.search` already
runs on. It would also need a migration owner, since ord-schema does not run alembic and
ord-app does.

CloudWatch Logs alone was rejected outright: there is no identifier to attach a thumb to,
so the feedback half of the requirement has nowhere to land. It remains the right home
for the operational half, where a structured line per ask gives error rate, p95 latency,
and token cost without a second store.

## Conclusions / next steps

In ord-schema:

- The record model, the sink protocol, and the four sinks.
- `Translation` as `translate`'s return type, `attempts` and `elapsed_ms` on
  `NLQueryError`, and `record_id` on `Answer`.
- A public corpus fingerprint on `Corpus`.
- A reader that folds thumb and label events onto their ask, derives `translation` and
  `repaired` from `attempts`, and a compaction command that rewrites a month of JSON
  objects into one Parquet file. The typed envelope makes that Parquet schema stable
  across months; a test should pin it, since the failure it prevents is silent.

In ord-infrastructure: a private bucket for internal data, holding the log under a
`nl-log/` prefix; a task role that may only `PutObject` under it; a separate read role for
analysis; and a lifecycle policy implementing whatever retention is chosen. Nothing in
the library names a bucket -- the sink takes one -- so this decision stays in the stack
where it can be reviewed.

In whatever serves `search.nl`: mint the session identifier client-side, and an endpoint
that records a thumb against a `record_id`.

Open questions, none of them blocking:

- **Retention.** Unset. It should be a decision rather than a default, since the records
  are free text people typed.
- **When to compact.** Volume is unmeasured. One object per ask at 100 questions a day is
  ~36k objects a year, which DuckDB reads slowly enough to notice; at a tenth of that it
  never matters. The reader should glob JSON and Parquet from the start so compaction can
  arrive late without a migration.
- **The maintainer surface.** A CLI that pages unlabeled records, or a notebook. The label
  event shape is the same either way.

## References

- [What constrains a natural-language layer over the search grammar](../2026-08-17-what-constrains-a-natural-language-layer/README.md) -- the layer this entry instruments, and why translation is checked rather than constrained
- [Where the agent search cache can live](../2026-08-15-where-the-search-cache-lives/README.md) -- the same question asked of a different piece of state
- [Natural-language query over the projection](../2026-07-31-nl-query-over-the-projection/README.md) -- the earlier framing of the layer
- [`ord_schema/search/nl.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/nl.py) -- translation, and the error taxonomy `outcome` mirrors
- [`ord_schema/search/nl_eval.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/nl_eval.py) -- the eval harness a labeled record is promoted into
- [`assets/parquet-compaction-probe.py`](assets/parquet-compaction-probe.py) -- the measurement behind the string payload
