# What the search API still needs before ord-interface can use it

- **Date:** 2026-10-02
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft; the three parity gaps are closed ([ord-schema#1091](https://github.com/open-reaction-database/ord-schema/pull/1091), [ord-schema#1092](https://github.com/open-reaction-database/ord-schema/pull/1092), [ord-schema#1093](https://github.com/open-reaction-database/ord-schema/pull/1093)), and result details and the eval re-run are open
- **Tags:** ord-schema, ord-interface, search, nl-query, rdkit, deployment
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`ord_schema.search` is on main and contained: the query grammar and its compiler, the
executor over the derived artifacts, `nl.ask`, the question log, and the eval harness,
with the corpus confined to its own trees since
[ord-schema#1087](https://github.com/open-reaction-database/ord-schema/pull/1087). The
plan is for ord-interface to replace its Postgres-backed search and `/ask` with it in one
move rather than refactoring twice
([2026-07-31](../2026-07-31-nl-query-over-the-projection/README.md)).

So: what does the API have to gain first, so that the swap takes nothing away from
what ord-interface answers today, and what can wait?

## Summary

**Three parity gaps and one decision. Latency is not one of them.**

- **Reaction SMARTS has no route.** ord-interface's `/query` and `/ask` take a reaction
  SMARTS and match it with the RDKit cartridge's `@>`. The grammar has no reaction-level
  predicate. This is the largest item, and it needs a design choice before any code.
- **Stereochemistry defaults the other way.** The executor always matches chirality:
  RDKit's `SubstructLibrary.GetMatches` defaults `useChirality` to `True`, and `Corpus`
  does not override it. ord-interface ignores chirality unless `use_stereochemistry` is
  set. Swapped as-is, every substructure query with a stereocenter would answer
  differently, and there would be no way to ask the old question.
- **A search cannot be narrowed to a dataset.** ord-interface filters on `dataset_id`;
  the projection has no column naming the dataset a reaction came from.
- **Where result details come from is undecided.** A search returns reaction IDs; the
  endpoints that render and download reactions read Postgres.

With pivot and occurrence artifacts, every canonical query repeats in under 0.23 s. Two
exceed a second on their first ask: the first query to reach a pivot level, which
`check_pivots()` at open removes, and a substructure screen for a common pattern, which
is RDKit's verification and is cached afterward. Without pivot artifacts, up to six
queries take 1.8–2.3 s on every ask, so a deployment needs them.

## Method

- **Parity.** ord-interface `QueryParams`
  ([`ord_interface/api/search.py`](https://github.com/open-reaction-database/ord-interface/blob/main/ord_interface/api/search.py))
  and `NLQuery`
  ([`ord_interface/api/nl_query.py`](https://github.com/open-reaction-database/ord-interface/blob/main/ord_interface/api/nl_query.py))
  at ord-interface `d5e6981`, read against the grammar in `ord_schema/search/query.py` at
  ord-schema `61c5443`. Every parameter either has a grammar equivalent or is listed
  below.
- **Chirality.** A three-molecule `SubstructLibrary` holding L-, D-, and
  unspecified alanine, queried with L-alanine's SMARTS through `GetMatches` with its
  default arguments and with `useChirality=False`.
- **Latency.** [`time_canonical.py`](assets/time_canonical.py) over the local corpus
  (53 datasets, 2,428,291 reactions; derived as in
  [2026-10-02](../2026-10-02-what-the-artifact-stamps-cannot-see/README.md#method)), on
  the 24 GiB laptop with DuckDB 1.5.5 and RDKit 2026.03.5. Raw numbers in
  [`timings.json`](assets/timings.json).

## Findings

### 1. Reaction SMARTS has no route

ord-interface's `ReactionSmartsQuery` joins `derived.reaction_smiles` to
`rdkit.reactions` and filters on `reaction @> reaction_from_smarts(%s)`. `QueryParams`
and `NLQuery` both carry the field, so it is reachable from the search form and from a
question in English.

The grammar's structure predicates all bind a single compound's `smiles`. The projection
does carry a reaction-level `smiles` — `message_helpers.derived_reaction_smiles`, with
agents removed, canonicalized, and atom mapping kept — but nothing matches against it.
Two ways to add one:

| | reaction match | per-compound decomposition |
| --- | --- | --- |
| what it compiles to | an RDKit reaction-substructure match against the reaction `smiles` | each reactant template as a substructure over the inputs, each product template over the products |
| what it needs | a screen for 2,428,291 reactions — a reaction fingerprint artifact — and a verify step | nothing new: the substructure library and the occurrence index |
| what it gives up | nothing | whatever the cartridge's `@>` checks beyond per-side substructure, atom maps included |
| cost | unmeasured | the cost of two or more substructure predicates |

Which one is right turns on a fact nobody has checked: **whether `@>` enforces atom maps
or role assignment beyond matching each side's templates.** If it does not, the
decomposition answers what ord-interface answers today at no new cost. That is the
first thing to measure, against the production database, before writing either.

**Decided: decomposition.** `@>` checks any one template per side, after a count of
molecules, and ignores atom maps
([2026-10-02](../2026-10-02-reaction-smarts-without-the-cartridge/README.md)), measured
on a throwaway cartridge and read from RDKit's source rather than against production.
Decomposition, with each template on a different molecule, answers what a query means
more closely than `@>` does. Merged in [ord-schema#1093](https://github.com/open-reaction-database/ord-schema/pull/1093).

### 2. Stereochemistry defaults the other way

| `GetMatches` call | matched |
| --- | --- |
| default arguments | L-alanine only |
| `useChirality=False` | L-, D-, and unspecified alanine |

`Corpus._substructure_ids` calls `GetMatches(molecule, numThreads=..., maxResults=...)`,
so the executor gets the first row. ord-interface's component query defaults
`use_chirality` to `False` and sets the cartridge's `rdkit.do_chiral_sss` only when a
caller passes `use_stereochemistry`, so it answers with the second.

The fix is small: a chirality flag on the substructure predicate, passed through to
`GetMatches`, and added to the match-set cache key — a cached achiral match set must not
answer a chiral question. The default is a decision. Off matches what ord-interface
answers today; on matches what a chemist who drew a stereocenter probably meant.

**Decided: on**, RDKit's default, because a stereocenter someone draws — in SMARTS now, in
a drawing tool planned beside the free-text box — is deliberate. `chirality: false` opts
out, and ord-interface keeps its answers by passing `use_stereochemistry` through as
that flag. Merged in
[ord-schema#1091](https://github.com/open-reaction-database/ord-schema/pull/1091).

### 3. No dataset filter

`QueryParams.dataset_id` becomes a `DatasetIdQuery` in ord-interface, and the dataset
pages depend on it. The projection is one file per dataset and names the dataset in
none of its 442 leaves, so no path reaches it. The executor already supplies one
per-file column the projection lacks — `structure_offset` — and could supply
`dataset_id` the same way, from the file each row came from; or the projection could
carry it. Either is small. The first keeps the artifact unchanged before it is
published; the second makes the column visible to anyone reading the Parquet directly.

**Built the first way**, from each projection's `ord.source_dataset_id` stamp, and merged
in [ord-schema#1092](https://github.com/open-reaction-database/ord-schema/pull/1092).

### 4. Where result details come from

`Corpus.search` returns `reaction_id`, or the group and measure columns of an aggregate.
ord-interface's `/reaction`, `/reactions`, and `/download_search_results` render and
export whole reactions from Postgres. Two ways to keep them working:

- **Keep Postgres for details.** The search runs on the artifacts and the details come
  from the database, which makes them two snapshots of ord-data that have to agree.
  `Corpus.fingerprint` can name the artifact snapshot; nothing yet compares it with
  what the database was loaded from.
- **Fetch by ID from the source Parquet.** A reaction's record is one row of its
  dataset's source file, which retires Postgres from the read path entirely. Not yet
  written or measured.

### 5. Latency

Each canonical query in `ord_schema.search.check` asked once on a freshly opened corpus,
then three more times; "repeat" is the median of those three.

| configuration | open | slowest first ask | slowest repeat | over 1 s on first ask |
| --- | ---: | ---: | ---: | --- |
| pivots and occurrences, default bound (1,000 rows) | 14.2 s | 1.34 s | 0.10 s | `nested_quantifiers`, `substructure_screen` |
| pivots and occurrences, unbounded | 13.8 s | 1.38 s | 0.23 s | the same two |
| occurrences, no pivots, default bound | 14.1 s | 2.50 s | 1.87 s | those two, `reduction_ordering`, `filtered_reduction` |
| occurrences, no pivots, unbounded | 14.5 s | 2.86 s | 2.30 s | those four, both quantifiers, `negation` |

The two first asks over a second have different causes, separated by asking them on a
fresh corpus with and without `Corpus.check_pivots()` at open:

| first ask | no warming | `check_pivots()` at open (24.6 s) |
| --- | ---: | ---: |
| `nested_quantifiers` | 1.37 s | 0.07 s |
| `existential_quantifier` | 0.74 s | 0.12 s |
| `substructure_screen` | 1.11 s | 1.11 s |

- **Reaching a pivot level is paid once per level per process**, by whichever query gets
  there first. `check_pivots()` reaches all 39 levels at open and takes the cost off
  every query.
- **The substructure screen is RDKit screening and verifying pyridine** against every
  distinct molecule in the corpus. Warming does not touch it. The match set is cached,
  so the repeat is 0.06 s; a new common pattern pays about a second once. The search
  README already calls that verification intrinsic.

The repeats match the last recorded figures — slowest 0.231 s with pivots and 1.87 s
without, over the then-19 canonical queries — against 0.23 s unbounded and 1.87 s bounded
here, so nothing merged since has moved latency. Unbounded costs more only where an
answer is large: `presence` returns 2,377,486 reactions and takes 0.16 s unbounded
against 0.004 s bounded.

### 6. What can wait

- **The eval.** 28 cases; the last full run scored Haiku and Sonnet 22/25 each, before
  several grammar additions
  ([ord-schema#1022](https://github.com/open-reaction-database/ord-schema/pull/1022)).
  Worth re-running before the swap rather than before anything else.
- **Paging.** Searches stop at `DEFAULT_MAX_ROWS` (1,000) and the grammar has no offset
  or cursor. ord-interface takes only a `limit` today, so this is not a parity gap; a UI
  that wants to page past a thousand reactions needs a cursor keyed on `reaction_id`.
- **Follow-up questions.** `nl.ask` answers one question at a time. Carrying the
  previous query forward ("now only those above 80%") is a feature, not a gap.

Deliberately out of scope, as the search README already says: free-text search over the
prose columns, arbitrary expressions, window functions, and joins.

## Conclusions / next steps

In order:

1. **Chirality — merged.** Add the flag and the cache-key change, and decide the
   default. This recommended off; the decision was on, with an opt-out (finding 2), in
   ord-schema#1091.
2. **Dataset filter — merged.** Supply `dataset_id` per file from the executor, the
   way `structure_offset` is supplied, unless the projection should carry it for readers
   of the Parquet. Built that way in
   [ord-schema#1092](https://github.com/open-reaction-database/ord-schema/pull/1092).
3. **Reaction SMARTS — merged.** Check what `@>` enforces, then pick between the two
   rows of finding 1: decomposition, in [ord-schema#1093](https://github.com/open-reaction-database/ord-schema/pull/1093).
4. **Result details.** Decide between Postgres and fetching from the source Parquet; the
   second wants a measurement of fetch-by-ID first.
5. **Re-run the eval** over all 28 cases.

Not on that list, because it is a deployment choice rather than API work: whether a
server calls `check_pivots()` at open. It costs 24.6 s once and removes the only
first-ask cost a corpus with pivot artifacts still has, which suits a long-lived server
and not a process that opens a corpus per job.

## References

- [`assets/time_canonical.py`](assets/time_canonical.py) and
  [`assets/timings.json`](assets/timings.json) — finding 5.
- [What should a natural-language query compile to?](../2026-07-31-nl-query-over-the-projection/README.md)
  and [Should a natural-language query compile to SQL, or to an IR?](../2026-08-07-query-ir-versus-generated-sql/README.md)
  — the design this builds on.
- [What to change in the artifact and search path before anything ships](../2026-08-30-artifact-and-search-path-review/README.md)
  — the pre-ship review whose findings are all closed.
- ord-schema [`ord_schema/search/README.md`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/search/README.md)
  — the grammar, the executor, and the containment.
- ord-interface [#203](https://github.com/open-reaction-database/ord-interface/pull/203)
  — the Postgres-backed `/ask` this would replace.
