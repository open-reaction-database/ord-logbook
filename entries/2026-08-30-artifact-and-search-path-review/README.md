# What to change in the artifact and search path before anything ships

- **Date:** 2026-08-30
- **Author:** Steven Kearnes
- **Status:** finding 1 closed, findings 3-6 open (finding 6 is still unmeasured)
- **Tags:** ord-schema, artifacts, search, duckdb, parquet, rdkit, deployment, caching
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

The artifact chain and the search executor are feature-complete enough to deploy, and
nothing has been deployed. No derived artifact has been pushed to ord-data's HuggingFace
mirror, so every format decision is still free and every one of them stops being free at
first publication.

So: read the whole path with that deadline in mind. What is cheap to change this week and
expensive to change ever after, and what is simply worth optimizing whenever?

## Summary

**The occurrence index should be a derived artifact, and that is the only finding here
with a deadline on it.** It is currently an 18,847,978-row DuckDB table built at open,
and it exists in memory rather than on disk for one reason: its `global_id` is
`structure_id` plus a per-dataset offset that is a running total over the corpus's pairs,
so the table belongs to no single dataset and cannot be written down. Store the
dataset-local `structure_id` instead, one file per dataset per indexed path, and the
offset becomes a join the corpus already performs — `Corpus._occurrences_from_pivot` has
done exactly that join since ord-schema#1004.

If it works, it removes the whole cold-start story: the 5–6.5 GB build floor, the 16–25 GB
of temporary files, the 1.19 GiB held for the life of the process, and the 3.3–58 s spent
at open. **Whether it works turns on one number nobody has measured** — what the semi-join
costs over Parquet rather than over an in-memory table.

**It works.** Measured over the full corpus, the artifact shape answers the semi-join in
**1.28× what the in-memory table costs** — 0.31 s against 0.15 s for pyridine over
`inputs.components`, the largest path — and the whole occurrence index is **256 MB of
Parquet** against 1.19 GiB held. See finding 1.

One other thing depends on no decision and should just be fixed: **`limit` is optional and
unbounded**, so a single query can materialize every matching `reaction_id` into an Arrow
table in process.

Everything else on the list is smaller.

**Shipped since this was written.** The artifact landed as
[ord-schema#1006](https://github.com/open-reaction-database/ord-schema/pull/1006) and the
`limit` bound as [#1005](https://github.com/open-reaction-database/ord-schema/pull/1005).
Derived over the full local corpus the tree is **253 MB (241 MiB) in 212 files** and holds
the same 18,847,978 rows the built index does. The `Corpus` reader that turns it into the
view — the half that actually collects the 1.19 GiB — is in flight; see
[status](#status).

## Method

A read of the artifact chain (`base`, `projection`, `structures`, `pivot`) and the search
path (`execute`, `query`, `sql`, `check`) at ord-schema `31bbe21`, plus both READMEs.

**One measurement, in finding 1**, by
[`measure_occurrences.py`](assets/measure_occurrences.py) over the full local corpus —
53 file pairs, 2,428,291 reactions, DuckDB 1.5.5 on the 24 GiB laptop, five rounds, medians
reported. Every other quantity is read out of the code or carried from
[the search cache entry](../2026-08-15-where-the-search-cache-lives/README.md) and
attributed where it is used. That matters because five figures in these documents have
previously been wrong through being carried forward rather than measured — the occurrence
index was off by 9×. Estimates below are marked as estimates.

## Findings

### 1. The occurrence index is an artifact wearing a table's clothes

`Corpus._occurrences` builds `occurrences` as one row per structure occurrence carrying
`(reaction_id, path, global_id, reaction_role)`. The first three columns are the whole
question; `global_id` is the one that cannot be written to a file.

The constraint is real and was learned expensively. An occurrence's corpus-wide ID is its
element's own plus its dataset's offset, and that offset is a running total over the
corpus's pairs — ordered by `source_md5`, so it is stable for a fixed dataset *set* and
renumbers when any dataset is added, removed, or rewritten. Baking it into a pivot would
produce IDs that stay in range beside a different set of datasets while aliasing another
dataset's molecules: passing on the full corpus, failing only on subsets.

But the constraint binds `global_id`, not the index. `structure_id` is dataset-local and
already written to every projection and structures artifact. An occurrences artifact
storing `(reaction_id, path, structure_id, reaction_role)`, one file per dataset per
indexed path, is derivable from the projection alone and carries nothing corpus-dependent.
The corpus then publishes

```sql
CREATE VIEW occurrences AS
SELECT o.reaction_id, o.path,
       (o.structure_id + f.structure_offset)::UINTEGER AS global_id,
       o.reaction_role
FROM read_parquet(<files>, filename=true) o
JOIN occurrence_offsets f ON o.filename = f.filename
```

which is the join `_occurrences_from_pivot` already writes, against a relation the
compiler already knows how to read: `_index_condition` emits
`reaction_id IN (SELECT reaction_id FROM occurrences AS occurrence WHERE ...)` and does
not care what `occurrences` is.

What it would remove, from the cache entry's measurements: 1.19 GiB held for the life of
the process, a 5–6.5 GB DuckDB `memory_limit` floor, 16–25 GB of temporary files, and the
3.3 s (from pivots) to 58 s (from projections) spent building. The container figure of
about 12 GiB is set by that build; without it the ceiling is the SubstructLibrary's
+2.4 GiB over a 1.09 GiB open corpus.

**The number that decides it, measured.** The semi-join was timed three ways over the same
18,847,978 rows: against the table built today, against one Parquet file per path carrying
`global_id` outright, and against the artifact shape — one file per dataset per path
holding the dataset-local `structure_id`, with the offset joined on by filename exactly as
`_pivot_offsets` keys a pivot. Four patterns spanning the range of match-set sizes, five
rounds, medians:

| pattern | matched | in memory | artifact shape | ratio |
| --- | --- | --- | --- | --- |
| `c1ccncc1` | 751,071 | 0.154 s | 0.310 s | 2.01× |
| `[OX2H]` | 2,050,645 | 0.253 s | 0.344 s | 1.36× |
| `C(=O)O` | 2,160,484 | 0.268 s | 0.351 s | 1.31× |
| `[#6]` | 9,449,792 | 0.925 s | 1.222 s | 1.32× |

Over `inputs.components`, the largest path. Summed across every path and pattern the
artifact shape is **1.28×** the in-memory table (3.609 s against 2.825 s), and the worst
single query is 1.222 s against 0.925 s. Every shape returned identical row counts
throughout.

Three things fall out of the full table. **The join is free**: the artifact shape and the
`global_id`-in-the-file shape are within noise of each other (3.609 s against 3.706 s), so
what costs anything is the scan, not the offset lookup. **The smallest path gets faster**,
not slower — `outcomes.products.measurements.authentic_standard` goes 0.015 s to 0.004 s,
because reading one path's files beats filtering `path = ?` across an 18.8 M-row table.
And **the whole index is 256 MB of Parquet** against the 1.19 GiB it holds in memory.

The shipped artifact drops the `path` column measured here — a file's path is stamped in
its footer and implied by where it sits, so no row needs to carry it — and comes to
**253 MB (241 MiB)** over the same rows.

Against my stated threshold — under about 0.5 s clearly worth it, at 2 s not — the
realistic queries land at 0.09–0.35 s and only `[#6]`, which matches essentially every
molecule in the corpus, reaches 1.2 s. **Worth doing.** What is bought for roughly 0.16 s
on a common query is the 5–6.5 GB build floor, the 16–25 GB of temporary files, the
1.19 GiB held, and the 2.7 s (or 58 s without pivots) at open.

One prior result is worth reading beside this. Building the index **per projection file**
was measured and rejected: it moves the memory floor to about 2 GB but is 68% slower and
holds 2.5 GiB more where nothing is constrained. That is not this proposal — the point
here is not to build it in smaller pieces but not to build it at all — but it is the
nearest thing already tried, and it says the shape of the build is not where the win is.

### 2. The rule that keeps corpus-wide IDs out of artifacts is not written down

ord-schema#1004 spent its design on carrying a source hash through pairing so that a pivot
could be joined to an offset rather than carrying one. The reasoning survives as a comment
in one function. It should be a stated rule in the artifacts README: *an artifact stores
dataset-local IDs; only a corpus assigns offsets, and only at open.*

The corollary is worth stating too. Because offsets renumber whenever the dataset set
changes, nothing outside a single open `Corpus` may cache anything keyed by `global_id`.
`Corpus.fingerprint` is the guard, and it changes exactly when the IDs do.

**Done** in #1006: the artifacts README now states the rule under *What pairs with what*.

### 3. `ARTIFACT_VERSION` is shared across every artifact type

`base.ARTIFACT_VERSION = "1"` is one version for projections, structures, and pivots
together, so a change to pivot derivation invalidates projections too — and re-deriving
projections over the 1.45 GB USPTO dataset is the expensive one.

The README's rationale is sound: a reader comparing two artifacts needs to know they were
built by one definition. But a fourth artifact is arriving, and the scheme is worth an
explicit decision rather than an inherited one — a per-artifact version beside a shared
compatibility version keeps the guarantee without making every change a full re-derive.
This is a decision about the scheme; **the version constant itself stays at `"1"` until
something is published.**

### 4. The match-set cache holds sixteen entries

The cache entry measures a pyridine search at 1.46 s end to end, of which roughly 1.4 s is
the RDKit screen and verify — nearly all of a common-pattern query. `Corpus._matches`
already caches that: an LRU of `_CACHED_MATCHES = 16` bitmaps keyed by the operation, the
parser, the resolved pattern, and the threshold, with a single-flight wait so a burst of
identical requests costs one pass rather than one each. It needs no corpus fingerprint in
the key, since it lives on the corpus whose IDs it is written against. The measurement run
for finding 1 exercised it incidentally and it behaves as described.

So the repeat-query win is already taken, and what is left is a sizing question. Sixteen
bitmaps is about 32 MB at ORD's scale — small enough that the bound is not protecting
much, and low enough that an agent working through a list of twenty reagents evicts its
own earliest answers before it finishes. Worth raising, and worth measuring the hit rate
under a real workload before guessing at the number. Not urgent, and not a format
decision.

### 5. The library build is 8 s of Python over a 0.08 s scan

`Corpus._library` loops in Python over all 2,016,224 structure rows, calling `to_pylist()`
per column per batch, to deduplicate 1,435,426 distinct SMILES through a dict. DuckDB can
do the deduplication: `GROUP BY smiles` with a `dense_rank()` gives `entry_of` as an Arrow
column convertible without Python iteration, leaving only the per-distinct-molecule
`AddBinary`/`AddFingerprint` calls that RDKit genuinely requires. **Estimated** 8 s → about
2 s; not measured.

Serializing the library as an artifact is the obvious alternative and does not work as
cleanly: its entry numbering is corpus-wide, and per-dataset libraries forfeit the
cross-dataset deduplication that turns 2,016,224 rows into 1,435,426 entries.

### 6. Similarity has no acceleration and no measurement

Substructure has the library; an exact structure predicate has the occurrence index.
`_similarity_ids` scans every structure's `morgan_fp` with a `bit_count` expression in
SQL, pruned only by the popcount band the threshold implies. A repeated similarity query
is served from the match cache in finding 4, so what is unaccelerated is the first ask of
each pattern and threshold. Nobody has measured it at corpus scale. It belongs on this
list rather than a later one because if it turns out to need acceleration, the fix —
banding, or a popcount-ordered layout — is another artifact decision.

### 7. Four smaller things worth fixing before a deployment depends on them

- **The timeout does not cover the expensive part.** `Corpus.search(timeout_seconds=)`
  starts its timer after name resolution, the library and index builds, screening, and
  verification. A caller setting a 10 s bound gets no protection from a 60 s screen. The
  docstring is explicit about this; the behavior is still a trap.
- ~~**`limit` is optional and unbounded**~~ — fixed in #1005. `Corpus(max_rows=)` bounds
  every search whether or not the query asked for a limit, and a result that comes back
  at the bound is logged as possibly cut short.
- **Nothing supports swapping a corpus.** A new dataset renumbers every structure ID, so
  the only correct move is to open a second `Corpus` and swap — which means peak memory is
  twice the steady state during a swap. That constraint is written down nowhere.
- **Execution still has no sandbox.** The search README lists this under "not yet solved";
  for a deployment it is a blocker rather than an open question.

## Conclusions / next steps

In order, and the first one is the only one with a deadline:

1. ~~Measure the Parquet semi-join.~~ Done, in finding 1: the artifact shape costs 1.28×
   the in-memory table and the index is 256 MB of Parquet. It clears the threshold.
2. ~~**Derive occurrences as an artifact**~~ — done in ord-schema#1006, and the ID rule
   from finding 2 is written down beside it. The format decision that had to precede
   publication is made.
3. ~~**Bound `limit`**~~ (finding 7) — done in ord-schema#1005.
4. ~~**Read the artifact.**~~ — ord-schema#1009, merged. Measured below: the view builds
   in 0.13 s against 2.86 s and leaves DuckDB holding 28 MiB against 1.66 GiB. **Finding 1
   is closed**; the format decision and the cost it was for have both landed.
5. Measure similarity (finding 6) before deciding whether it needs an artifact of its own.

Findings 3, 5, and the rest of 7 are worth doing and are not on the critical path.

## Status

| # | finding | state |
| --- | --- | --- |
| 1 | occurrence index as an artifact | done: written by ord-schema#1006, read by #1009 |
| 2 | dataset-local ID rule unwritten | done, artifacts README |
| 3 | `ARTIFACT_VERSION` shared | open; stays `"1"` until something is published |
| 4 | match-set cache holds sixteen | open, needs a hit rate under a real workload |
| 5 | library build is 8 s of Python | open, estimated 8 s → 2 s |
| 6 | similarity unaccelerated, unmeasured | open, unmeasured |
| 7 | timeout, `limit`, corpus swap, sandbox | `limit` done in #1005; the other three open |

The reader is the half that pays, and it is measured. `Corpus(occurrences_dir=...)`
publishes the index as a **view over Parquet** where every indexed path is covered, and
materializes it otherwise — a view whose branches unnest the projection would repeat that
traversal on every query rather than once. Merged as
[ord-schema#1009](https://github.com/open-reaction-database/ord-schema/pull/1009).

Over the full local corpus, with the substructure library left unbuilt so the index is the
only thing being measured:

| | table (from pivots) | view |
| --- | --- | --- |
| index build | 2.86 s | **0.13 s** |
| resident added | 1.92 GiB | **0.32 GiB** |
| DuckDB holds | +1.66 GiB | **+28 MiB** |
| peak RSS | 5.61 GiB | **4.58 GiB** |

Two things are worth reading carefully here. **The table figure is the fast one** — built
from pivot artifacts, not from projections, which is 59 s. Against that baseline the view
is 22× faster to reach and holds a sixtieth of the DuckDB memory.

And **peak RSS falls by only 1.03 GiB, not by the 1.92 GiB the table adds.** The
difference is the scan the index check makes either way: `count(DISTINCT global_id)` over
18,847,978 rows, which the view pays out of Parquet. That check is what makes the index
trustworthy — it is the thing that catches a traversal reaching nothing — so it stays, and
the honest headline is that the view removes the *held* gigabyte and a half rather than the
whole peak. The peak that matters for sizing is still the SubstructLibrary's, which this
does not touch.

One thing the review turned up that is worth recording, because it is the assumption the
whole chain rests on. A reviewer objected that an occurrences artifact carries
projection-build-local `structure_id`s and is accepted on source hash alone, so a rebuild
could leave it current but pointing at different molecules — undetectably, since a
permutation leaves the distinct-ID count unchanged. The mechanism does not fire:
assignment is first-seen order over an insertion-ordered dict, a pure function of the
source bytes, the ord-schema version, and the RDKit that canonicalized the SMILES, all
three stamped. Rebuilding one dataset three times gives an identical `(structure_id,
smiles)` mapping.

But **nothing asserted that**, and the artifacts README said the opposite — "IDs are not
stable across builds" — which read literally denies the property the pairing design
depends on. Both are fixed: there is now a test that fails if assignment becomes
non-deterministic, and the README says what is actually guaranteed (stable for a fixed
source and library, not across an upgrade that changes canonicalization, which is what
the version stamps are for).

Per-query cost is comparable in both directions and does not resolve cleanly at this
corpus size — 0.10 s against 0.06 s for pyridine, 0.15 s against 0.11 s for `[#6]`, and the
view ahead on two of four patterns. The 1.28× measured in finding 1 remains the figure to
quote; these runs are too close to separate.

## References

- [`assets/measure_occurrences.py`](assets/measure_occurrences.py) — times the semi-join
  against all three shapes; [`assets/semijoin-timings.log`](assets/semijoin-timings.log)
  is the run finding 1 reports.
- [Where the agent search cache can live](../2026-08-15-where-the-search-cache-lives/README.md)
  — the source of every memory and latency figure quoted here that finding 1 did not
  measure.
- [The projection search index](../2026-07-31-projection-search-index/README.md) and
  [EAV versus projection](../2026-07-31-eav-versus-projection/README.md) — the pivoted fact
  table this all descends from.
- ord-schema#1004 — reading the occurrence index from pivot artifacts, where the
  offset-belongs-to-no-artifact constraint was worked out.
- `ord_schema/artifacts/README.md` and `ord_schema/search/README.md` at ord-schema
  `31bbe21`.
