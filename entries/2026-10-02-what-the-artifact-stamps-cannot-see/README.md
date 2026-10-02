# What the artifact stamps cannot see

- **Date:** 2026-10-02
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5)
- **Status:** final; the open item is how the two undecided day/month verdicts get applied
- **Tags:** ord-schema, artifacts, provenance, staleness, datetime, data quality
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

A derived artifact is *stale* when its source has moved on, and the footer stamps exist
so that condition is detectable without reading column data. Re-deriving the corpus after
[#1018](https://github.com/Open-Reaction-Database/ord-schema/pull/1018) added a parsed
`timestamp` beside every `DateTime` string, the chain reported success and left half the
tree at the old schema.

So: which changes do the stamps actually catch, and which ones look identical to a file
that is up to date?

## Summary

**Three classes of change, and the stamps catch only the first.** A change to the *source
data* moves `ord.source_md5` and is caught. A change to an artifact's *columns* is invisible
to the stamps and caught instead by `base.missing_columns`, which compares the declared
schema against the file's — the mechanism that made #1018's new column rebuild 49 of 53
projections without a version bump. A change to a *derivation input that lives in code* is
caught by nothing.

**That third class has exactly one member today, and it is live.** `projection._DAY_FIRST`
and `projection._UNDECIDED` decide per dataset whether `NN/NN/NNNN` reads day-first. Moving
a dataset between them changes every timestamp the projection writes for it and moves
nothing that is stamped. Verified with
[`probe_freshness.py`](assets/probe_freshness.py): after settling either undecided verdict
in code, `is_current` is `True`, `missing_columns` is empty, and `stamps_are_current` is
`True`. The 9,656 dates those two projections spell and do not parse would stay null
forever.

**The orientation table is also mostly redundant.** Of the four hardcoded day-first
verdicts, **three** are ones the value scan reaches on its own; only `2be11f57` needs
telling, and the [normalization proposal](../2026-09-03-date-time-formats/README.md#proposal)
rewrites it in source. So the table empties on its own once that lands — except for the two
datasets the rewrite deliberately skips.

**Recommendation: apply those two verdicts in the source data, not in the table.** A second
pass of the same rewrite over 0.7 MB makes staleness work by the mechanism that already
works, and needs no new stamp. Stamping a per-dataset derivation key is the right fix only
if the verdict will live in code permanently.

## Method

Probes over the local corpus at `~/ord/artifacts`, derived from
[ord-data `83f971f`](https://github.com/Open-Reaction-Database/ord-data/commit/83f971f) with
ord-schema at the merge of
[#1037](https://github.com/Open-Reaction-Database/ord-schema/pull/1037).

[`probe_freshness.py`](assets/probe_freshness.py) asks the freshness check three questions:
what it answers when an undecided verdict is settled the way a one-line edit to the table
would settle it; how many dates the affected projections currently spell but do not parse;
and which hardcoded day-first verdicts the value scan would reach without the table. It
restores the tables it perturbs, so it is safe to re-run.

The timings come from the re-derive itself, over the 53-dataset corpus whose largest source
is 89% of its bytes.

## Findings

### 1. The stamps answer two questions, and column drift is neither

Every artifact carries four required stamps — `ord.artifact`, `ord.artifact_lineage`,
`ord.source_md5`, `ord.ord_schema_version` — plus `ord.rdkit_version` where RDKit was
involved. `is_current` compares the source hash and, through `stamps_are_current`, the
artifact name, lineage, library version, and RDKit version.

Between them they answer *where did this come from* and *who wrote it*. A column added to an
artifact's definition changes neither: a file written before the column stamps exactly like
one written after. `missing_columns` is what sees it, comparing declared paths **and leaf
types** down through structs, lists, and maps — the nesting matters, because the projection
is one struct per message and a top-level comparison would call a file current that is
missing nearly everything.

### 2. A subset run leaves the rest of a split artifact behind

Pivots and occurrences are one artifact per *(dataset, level)* and *(dataset, path)*, and
both derivations take a flag naming a subset. The documented pipeline uses it: the pivot step
is driven by `derive_occurrences --print_levels`, which names the four levels the occurrence
index reads, while the corpus on disk holds all 39.

After #1018, five levels gained `element…timestamp` — `inputs.components.analyses`,
`outcomes.analyses`, `outcomes.products.measurements.authentic_standard.analyses`,
`provenance.record_modified`, and `workups.input.components.analyses`. None of the five is
among the four the pipeline names. The chain rebuilt the projections, exited 0, and left
those five at the old schema; a quantifier over one then failed with
`BinderException: Could not find key "timestamp" in struct` — a message naming a struct key
rather than the file that predates it.

Worth separating the two things that went wrong, because only one was a bug. The freshness
check was never broken: the four levels the run named genuinely have no timestamp field and
were correctly skipped. What was missing was any signal that the *other* 35 existed. Fixed in
[#1036](https://github.com/Open-Reaction-Database/ord-schema/pull/1036): `Corpus` refuses an
artifact short a declared column with a message that names it, and both derivations refuse to
finish when the tree holds a key the run did not cover that is short one. The cost is
negligible — 0.98 s to scan 35 uncovered levels, 7 ms per level of 53 artifacts on the read
side.

[#1037](https://github.com/Open-Reaction-Database/ord-schema/pull/1037) then collapsed the
three hand-written copies of that per-file check into one, which is the general lesson: the
column check had reached the projections and structures but not the pivots, because the
contract was written three times and only two copies were complete.

### 3. A verdict settled in code is invisible

The case the stamps cannot reach. `slash_orientation` decides per dataset, before any row is
projected, whether slash dates read day-first; the answer comes from a value scan, or from
`_DAY_FIRST` / `_UNDECIDED` where the scan cannot settle it. An undecided dataset gets `None`,
and every `DateTime` in it projects with a null `timestamp`.

Settling one in code — the one-line edit the open status in the date-time entry invites —
changes the values the projection would write and nothing that is stamped:

| probe | `5c9a1032` | `5e8318f0` |
| --- | --- | --- |
| `is_current` after settling the verdict | **True** | **True** |
| `missing_columns` | `[]` | `[]` |
| `stamps_are_current` | True | True |
| rows | 9,632 | 24 |
| `record_created` dates spelled | 9,632 | 24 |
| …of those, parsed | **0** | **0** |

The source bytes have not moved, so the hash is right; the schema has not moved, so the
columns are right; no version was bumped, so the lineage is right. Nothing is wrong except
the data, and nothing looks at the data.

This is worse than the column case in one respect: a missing column fails loudly at bind
time, as finding 2 shows. A projection that answers "no date recorded here" for 9,656
reactions fails silently, and a temporal query simply returns fewer rows than it should.

### 4. Three of the four hardcoded verdicts are already redundant

The table asserts what the scan can often work out for itself:

| dataset | table says | scan alone says | in the proposal's rewrite? |
| --- | --- | --- | --- |
| `172039a7` | day-first | **day-first** | no — holds no ambiguous values |
| `3b8a2ef3` | day-first | **day-first** | no |
| `c5b00523` | day-first | **day-first** | no |
| `2be11f57` | day-first | undecided | **yes** |

Three entries are cross-checks rather than inputs: the code already raises if a listed
dataset's scan contradicts the table, which is worth keeping while the table exists, but the
verdict itself is not load-bearing. Only `2be11f57` genuinely depends on being told, and the
ambiguous-scope rewrite normalizes it in source.

So `_DAY_FIRST` empties once the rewrite lands. The *scan* stays: 551,696 slash values
survive the rewrite, all self-resolving, and reading them is what `day_first_dates` is for. It
is the hardcoded verdicts that go, not the orientation logic.

### 5. What the re-derive cost, measured

For sizing any future rebuild, over the 53-dataset corpus:

| step | wall clock | written |
| --- | ---: | --- |
| projections | **49 min 8 s** | 49 of 53 |
| structures | 1 s | 0 — verified byte-identical |
| pivots, 4 levels, no force | 4 s | 0 |
| pivots, 39 levels, forced | **31 min 36 s** | 2,279 artifacts |
| occurrences, forced | 4 s | 0 |

Structures skipping was correct, not a second instance of finding 2: a forced re-derive of
two datasets' structures produced files identical in every column, so adding a timestamp to
the projection does not perturb `structure_id` assignment. The projection step is dominated by
one 1.0 GB source that is 89% of the corpus by bytes, so across-dataset parallelism is
Amdahl-capped at about 1.13x — worth knowing before anyone proposes it.

## Conclusions / next steps

1. **Resolve the two open verdicts in the source data.** 9,656 reactions, 0.7 MB, a second
   pass of the rewrite the [date-time entry](../2026-09-03-date-time-formats/README.md#the-rewrite)
   already specifies. Editing `_UNDECIDED` instead leaves the projections stale and silent,
   per finding 3.
2. **Delete `_DAY_FIRST` when the ambiguous-scope rewrite lands.** Finding 4 shows three of
   four entries are redundant now and the fourth is fixed by the rewrite.
3. **Only then consider a per-dataset derivation key.** A stamp recording the choices a
   derivation made would close finding 3 in general, and after steps 1 and 2 the class has no
   members. Build it if a per-dataset decision is ever meant to live in code permanently; it
   is the wrong trade for a category about to be empty.
4. **A re-derive is still the moment to re-record the canonical baseline.** `corpus_baseline.json`
   is keyed to a corpus digest, and the pending `temporal_range` canonical query needs a corpus
   that can answer it, so both want the source fix to land first rather than being pinned twice.

## References

- [`probe_freshness.py`](assets/probe_freshness.py) — the three probes, re-runnable
- [Date and time formats across the corpus](../2026-09-03-date-time-formats/README.md) — the
  orientation verdicts, the normalization proposal, and the two datasets it skips
- [Artifact and search path review](../2026-08-30-artifact-and-search-path-review/README.md) —
  finding 3 on version granularity, whose recommendation shipped as `ord.artifact_lineage`
- [Derived Parquet sidecars](../2026-07-25-derived-parquet-sidecars/README.md) — where the
  stamps and wholesale invalidation were first proposed
- ord-schema [#1018](https://github.com/Open-Reaction-Database/ord-schema/pull/1018) — the
  parsed `timestamp` that prompted this
- ord-schema [#1036](https://github.com/Open-Reaction-Database/ord-schema/pull/1036),
  [#1037](https://github.com/Open-Reaction-Database/ord-schema/pull/1037) — the column check
  and the collapse
