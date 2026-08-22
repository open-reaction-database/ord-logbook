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

**An append-only event log of JSON objects in S3**, under the `open-reaction-database`
bucket the backend stack already provisions, read with DuckDB. Three event kinds share a
`record_id`: the **ask**, written by the library; the **thumb**, from an anonymous
visitor; the **label**, from a maintainer. Results are not stored -- the translation and a
corpus fingerprint reproduce them on demand.

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

This is a design record rather than a measurement: no probe was run, and the entry argues
from constraints that are already true of the deployed system. Each was read out of the
stacks or the code rather than assumed:

| Claim | Where it was verified |
| --- | --- |
| The live NL endpoint's whole record is one stdout line | `ord_interface/api/nl_query.py` on ord-interface `origin/main` |
| `search.nl` records nothing, and discards `response.usage` | [`ord_schema/search/nl.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/nl.py) |
| `Corpus` exposes no version or fingerprint | [`ord_schema/search/execute.py`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/execute.py) -- stamps are read at construction and indexed by `source_md5`, never surfaced |
| The bucket already exists and is protected | `stacks/backend/__main__.py`, `aws.s3.Bucket("ord_bucket", bucket="open-reaction-database")` |
| The dated corpus database is one of four on a shared cluster | `stacks/database/README.md` |
| The cluster is a 2-vCPU `db.t4g.large` chosen for RAM | `stacks/backend/README.md`, "Database sizing" |

The one number that is *not* verified is volume, and it matters only for compaction; see
[Conclusions](#conclusions--next-steps).

## Findings

### The record

Three event kinds, one JSON object each, all carrying `record_id`. Only the ask is
written by the library.

```json
{
  "event": "ask",
  "record_id": "0f3c…",          "session_id": "a91b…",   "timestamp": "2026-08-22T18:04:11Z",
  "question": "which reactions use pyridine as a solvent?",
  "translation": {"where": {"op": "exists", "path": "inputs.components", "…": "…"}},
  "outcome": "empty",
  "row_count": 0,
  "repaired": true,
  "declined_reason": null,       "declined_attempted": false,
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

Nothing identifying is stored beyond a session identifier the client mints: no IP
address, no user agent, no account. Questions are free text a person typed, which is
reason enough for the design to state a retention period rather than let one accrete by
default.

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

`declined_attempted` is already carried on `UnanswerableError` and is worth persisting
for the same reason it exists: declining after the compiler refused a guess is a
different event from reading the question and saying no, and only the second is the
behavior the layer is trying to have.

The session identifier is what turns isolated pairs into something you can learn from.
Grouped by session, the log shows the reformulation chain -- *asked X, got nothing,
rephrased to Y, rephrased to Z, stopped* -- and the user's own next attempt is a free
approximate label on the previous failure. That signal cannot be reconstructed later from
unlinked records, which is the argument for minting the identifier before there is any
service to use it.

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
class Translation:
    query: query.Query
    usage: Usage
    repaired: bool
    elapsed_ms: float

def translate(question, ...) -> Translation
def ask(question, corpus, *, session_id=None, sink=None, ...) -> Answer
```

The failure paths are the ones that make this the better shape rather than merely the
tidier one. A record is most interesting exactly when the translation *didn't* work, and
a malformed query that burned two turns has spent real money -- but an exception carries
no return value, so an accumulator was the only way to get the usage back out. Instead
`NLQueryError` grows `usage` and `elapsed_ms`, and every path reports what it cost,
whether it ended in a query, a refusal, or a compiler error.

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
- `Translation` as `translate`'s return type, `usage` and `elapsed_ms` on `NLQueryError`,
  and `record_id` on `Answer`.
- A public corpus fingerprint on `Corpus`.
- A reader that folds thumb and label events onto their ask, and a compaction command
  that rewrites a month of JSON objects into one Parquet file.

In ord-infrastructure: the `nl-log/` prefix, a write-only task role, a read role for
analysis, and a lifecycle policy implementing whatever retention is chosen.

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
