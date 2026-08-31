# What to change in the artifact and search path before anything ships

- **Date:** 2026-08-30
- **Author:** Steven Kearnes
- **Status:** draft (a review, not a measurement; the one number it turns on is not yet measured)
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

Two other things are worth doing and depend on no decision. A **match-set cache** is the
biggest per-query win available: the RDKit screen and verify is roughly 1.4 s of a 1.46 s
pyridine query and is recomputed in full for every identical query, with `Corpus.fingerprint`
already sitting there as the correct cache key. And **`limit` is optional and unbounded**,
so one query can materialize every matching `reaction_id` into an Arrow table in process.

Everything else on the list is smaller.

## Method

A read of the artifact chain (`base`, `projection`, `structures`, `pivot`) and the search
path (`execute`, `query`, `sql`, `check`) at ord-schema `31bbe21`, plus both READMEs.

**No new measurements.** Every quantity below is either read out of the code or carried
from [the search cache entry](../2026-08-15-where-the-search-cache-lives/README.md), and
is attributed where it is used. That matters because five figures in these documents have
previously been wrong through being carried forward rather than measured — the occurrence
index was off by 9×. Nothing new is asserted as measured here, and the estimates are
marked as estimates.

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

**The number that decides it.** The semi-join currently reads an in-memory table. Over
Parquet it reads one path's rows — `inputs.components` is the largest — with `path = ?`
prunable to whole files if the artifact is partitioned by path, but `get_bit(...)` on a
computed `global_id` not pushable at all. The cache entry puts the current indexed
reaction lookup at 0.2 s against 3.5 s unindexed. **Under about 0.5 s the trade is clearly
worth it; at 2 s it is not.** This is measurable tonight on the local corpus and should be
measured before any of it is built.

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

### 4. The screen and verify are recomputed for every identical query

The cache entry measures a pyridine search at 1.46 s end to end, of which roughly 1.4 s is
the RDKit screen and verify — nearly all of a common-pattern query. That work is repeated
in full every time the same question is asked. The only cache in `execute.py` is DuckDB's
`parquet_metadata_cache`; compound-name resolution is cached per search, not across
searches.

An LRU keyed by `(fingerprint, kind, pattern, threshold)` returning the match-set bitmap
takes a repeat query down to the SQL alone. For a consumer that is an agent asking a
stream of related questions — the consumer this was built for — that is the largest
user-visible improvement available, and it adds nothing to the artifacts.

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
SQL, pruned only by the popcount band the threshold implies. Nobody has measured it at
corpus scale. It belongs on this list rather than a later one because if it turns out to
need acceleration, the fix — banding, or a popcount-ordered layout — is another artifact
decision.

### 7. Four smaller things worth fixing before a deployment depends on them

- **The timeout does not cover the expensive part.** `Corpus.search(timeout_seconds=)`
  starts its timer after name resolution, the library and index builds, screening, and
  verification. A caller setting a 10 s bound gets no protection from a 60 s screen. The
  docstring is explicit about this; the behavior is still a trap.
- **`limit` is optional and unbounded** (`query.Query.limit` defaults to `None`). A query
  without one materializes every matching `reaction_id` into an Arrow table in process.
- **Nothing supports swapping a corpus.** A new dataset renumbers every structure ID, so
  the only correct move is to open a second `Corpus` and swap — which means peak memory is
  twice the steady state during a swap. That constraint is written down nowhere.
- **Execution still has no sandbox.** The search README lists this under "not yet solved";
  for a deployment it is a blocker rather than an open question.

## Conclusions / next steps

In order, and the first one is the only one with a deadline:

1. **Measure the Parquet semi-join** against the in-memory table on the full local corpus.
   That number decides finding 1, and finding 1 decides how much memory a container needs.
2. If it lands, **derive occurrences as an artifact**, partitioned by path, and write down
   the ID rule from finding 2 beside it.
3. **Cache match sets** (finding 4) and **bound `limit`** (finding 7) — neither waits on
   anything.
4. Measure similarity (finding 6) before deciding whether it needs an artifact of its own.

Findings 3, 5, and the rest of 7 are worth doing and are not on the critical path.

## References

- [Where the agent search cache can live](../2026-08-15-where-the-search-cache-lives/README.md)
  — the source of every memory and latency figure quoted here.
- [The projection search index](../2026-07-31-projection-search-index/README.md) and
  [EAV versus projection](../2026-07-31-eav-versus-projection/README.md) — the pivoted fact
  table this all descends from.
- ord-schema#1004 — reading the occurrence index from pivot artifacts, where the
  offset-belongs-to-no-artifact constraint was worked out.
- `ord_schema/artifacts/README.md` and `ord_schema/search/README.md` at ord-schema
  `31bbe21`.
