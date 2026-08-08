# A local PubChem name lookup: 8 minutes to build, identical answers, 6 ms per name

- **Date:** 2026-08-08
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** resolvers, pubchem, name-resolution, duckdb, parquet, sqlite, rate-limits, data-packaging

## Question

`ord_schema.resolvers` resolves compound names to SMILES by calling PubChem's PUG REST
service first, then NCI/CADD CIR, then OPSIN. PubChem rate-limits us from time to time,
and CIR has been unreliable — [2026-07-11](2026-07-11-name-only-compounds.md) found it
down, and wrong when it was up. PubChem publishes its whole compound corpus as bulk
files. Can we download those and build a local lookup — a SQLite data package, or a
Parquet file we query with DuckDB — that answers the same question without the network?

Two follow-ups, answered in findings 5, 9, and 10: if we ship one artifact rather than
two, which one; and should the local lookup unify all three sources — PubChem, NCI/CADD,
and EBI — rather than just PubChem?

## Summary

**Yes, and it is cheaper than expected: 2.3 GB of downloads and six minutes of build
produce an index that returns exactly the same structures PubChem's service returns, at
6 ms a lookup instead of 177 ms. Ship it as a single 806 MiB Parquet, and wire it in as a
tier in front of the existing chain rather than as a replacement for it, with the curated
dictionary still ahead of both.** The reasons to be careful are about answer quality, not
about speed or feasibility — and the answer to unifying it with CIR and ChEMBL is no, for
reasons that turn out to be concrete rather than aesthetic.

- **The whole thing is 8 minutes.** `CID-Synonym-filtered.gz` (921 MB) and
  `CID-SMILES.gz` (1.4 GB) download in 123 s and build in 359 s into a 117,292,483-name
  index. As ZSTD Parquet that is **1.9 GiB**; dropping vendor catalog codes and other
  machine identifiers takes it to **806 MiB** without losing a single name ORD uses.
- **It is not an approximation of the service — it is the same answers.** On 700 names
  probed against live PUG REST, every one of the **123 names both answered agreed on the
  exact structure** after RDKit canonicalization. Zero disagreements, zero local-only
  answers. The three names the service answered and the index missed were all one bug:
  a Unicode prime.
- **Ship one artifact: the Parquet.** SQLite point lookups are the fastest thing here by
  a distance — **8 µs** (p50, warm) against PubChem's 177 ms — but the gap stops
  mattering once the Parquet is written with 50k-row groups instead of 1M: point lookups
  drop from 64 ms to **6.3 ms**, for 0.2% more bytes. That is 28× faster than the service
  it replaces, it reads from `pyarrow` (already an ord-schema dependency) as well as
  DuckDB, and it is **806 MiB against SQLite's 4.87 GiB**. The SQLite is derivable from
  the Parquet in 42 s if a caller ever needs microseconds, so shipping it is redundancy,
  not coverage.
- **On our actual backlog it adds 4.4 points of row coverage.** Against the 864,997
  name-only rows, the 2026-07-11 curated dictionary plus OPSIN reached 10.0%; adding the
  local index reaches **14.5%** (3,047 new names, 38,346 new rows). Useful, not
  transformative — the ceiling is still that most name-only rows are not compounds.
- **The failure mode is inherited, and speed makes it worse.** PubChem's synonym table
  is depositor-supplied, so it maps paper-local labels and functional-class words onto
  arbitrary specific structures. Of the **60 highest-impact hits, 23 are collisions of
  this kind** — `anhydride` → a nucleotide, `4A` → a benzothiazine, `thiol` → hydrogen
  sulfide, `II` → a dipeptide. That is 13.2% of the reviewed rows getting a confidently
  wrong structure, now for free and off the network. This is the same failure 2026-07-11
  caught in CIR (`TEA` → triethanolamine), and the same answer applies: **a curated
  dictionary in front of any lookup service, local or remote.**
- **Rate limits are not what makes this worth doing.** Paced at 3 requests/second the
  service never throttled us across 700 requests — PubChem's own header stayed green at
  ~20% of the request budget the whole way. A one-time online pass over the entire
  46,831-name backlog is about **4 hours**, which is annoying but not a blocker. The
  case for local is the **interactive path**: `ord-interface`'s NL query resolves a
  user's compound name on the request path, where 177 ms plus a 10 s timeout plus a
  three-service fallthrough is the difference between a query and a spinner, and where a
  429 is a user-visible failure rather than a slow batch job.
- **Do not try to unify PubChem with CIR and ChEMBL.** CIR publishes no name index at all
  — the only NCI bulk file is a 266k-record database from 2012 — and it is not usable as
  a fallback either: a paced probe at 3 requests/second got **368 dropped TLS connections
  out of 400** and left the host blocking us afterwards. That reframes 2026-07-11's "CIR
  was down" as **"we had tripped CIR's block."** ChEMBL is 96.3% already inside the
  PubChem index, adds **36 ORD names (387 rows, 0.1%)**, and **disagrees with PubChem on
  34% of the names both resolve** — so the merge buys less than the conflict-resolution
  problem it creates. The names still missing after PubChem (`TEA`, `petroleum ether`,
  `NaSO4`, `xylenes`) are abbreviations, typos, and mixtures that no third structure
  database indexes. **The missing tier is a curated ORD reagent dictionary, not another
  source.**

Two further results, both independent of whether we build the index:

- **OPSIN should be a library call, not an HTTP call — and its defaults are safer than
  the web service's.** The jar via `py2opsin` parses all 46,831 names in **2.3 s in one
  JVM** (0.05 ms/name). It also declines 456 names the EBI service answers, because the
  service runs with radicals enabled and returns **`methyl` → `[CH3]`, `bromo` → `[Br]`,
  `Boc` → `[C](=O)OC(C)(C)C`** — substituent fragments that RDKit accepts and
  `resolve_names` writes as compound structures. **27% of the 1,663 OPSIN hits in
  2026-07-11 are these radicals.** The catch: a JVM start costs 230 ms, so one name per
  process is *worse* than the HTTP call it replaces. Local OPSIN is a batch win, not an
  interactive one.
- **Three ord-schema bugs, filed:**
  [#952](https://github.com/open-reaction-database/ord-schema/issues/952) (a multi-CID
  PubChem response is silently resolved to the first CID — `II` and `IV` do this today),
  [#953](https://github.com/open-reaction-database/ord-schema/issues/953) (the OPSIN
  radicals above), and
  [#954](https://github.com/open-reaction-database/ord-schema/issues/954)
  (`_pubchem_resolve` asks for `IsomericSMILES`, which PubChem has renamed to `SMILES`;
  the alias still works, so this is hygiene).

## Method

- **Source data:** the 2026-08-08 regeneration of
  [`CID-Synonym-filtered.gz`](https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-Synonym-filtered.gz)
  (921 MB, `cid⇥synonym`) and
  [`CID-SMILES.gz`](https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-SMILES.gz)
  (1.4 GB, `cid⇥isomeric SMILES`) from PubChem's `Compound/Extras` FTP tree. Per
  `README-Extras`, both are regenerated in full with every PubChem dump, so a refresh is
  a re-download rather than a diff. NCBI places no restrictions on redistribution.
  *Filtered* rather than *unfiltered* synonyms: the filtered list has names PubChem
  considers inconsistent with the structure already removed, and is 600 MB smaller.
- **Index build** ([`build_index.py`](../assets/2026-08-08-local-pubchem-name-lookup/build_index.py)):
  DuckDB reads both gzip files directly, lowercases and trims each synonym, collapses to
  one CID per name, joins to the SMILES table, and writes a name-sorted ZSTD Parquet plus
  a `WITHOUT ROWID` SQLite table keyed on the name. Lowercasing matches the
  case-insensitivity of PubChem's REST name lookup. Where a name matches several CIDs the
  index keeps the lowest, PubChem's oldest record for that name, and stores the match
  count so a caller can treat an ambiguous hit differently.
- **Evaluation set** ([`prep_testset.py`](../assets/2026-08-08-local-pubchem-name-lookup/prep_testset.py)):
  the 46,831 names from [2026-07-11](2026-07-11-name-only-compounds.md) that survived
  junk filtering, joined to their ORD row counts and to what OPSIN/CIR made of each. That
  entry ran with PubChem deliberately skipped, so its misses are exactly the population
  this index is supposed to serve.
- **Live baseline** ([`probe_api.py`](../assets/2026-08-08-local-pubchem-name-lookup/probe_api.py)):
  the same URLs `_pubchem_resolve` and `_cactus_resolve` build, paced at 3
  requests/second against PubChem's documented ceiling of 5/second and 400/minute. Three
  samples: 400 names drawn from the 2026-07-11 misses, the 300 candidate names carrying
  the most ORD rows, and — against CIR — 400 names the local index failed to resolve.
  Each response's `X-Throttling-Control` header, line count, and wall time are recorded.
- **Scoring** ([`eval_lookup.py`](../assets/2026-08-08-local-pubchem-name-lookup/eval_lookup.py)):
  coverage by name and by ORD row; agreement with the live probes compared as RDKit
  canonical SMILES, which is the form `resolvers.canonicalize_smiles` writes, so two
  spellings of one molecule count as agreement and a different molecule does not; and
  lookup latency for both storage forms, cold and warm.
- **Quality review** ([`review_top_hits.py`](../assets/2026-08-08-local-pubchem-name-lookup/review_top_hits.py)):
  the 60 hits with the most ORD rows behind them, graded by hand as `ok` or `label`.
  Verdicts are recorded in the script so the judgement is visible and re-runnable.
- **Local OPSIN** ([`bench_opsin.py`](../assets/2026-08-08-local-pubchem-name-lookup/bench_opsin.py)):
  `py2opsin` 1.2.0 on conda-forge `openjdk` 25.0.2, run both as one JVM over the whole
  candidate set and as one JVM per name, and swept across OPSIN's permissiveness flags
  against the 2026-07-11 web-service results.
- **Other sources** ([`chembl_overlap.py`](../assets/2026-08-08-local-pubchem-name-lookup/chembl_overlap.py)):
  `molecule_synonyms` joined to `compound_structures` from the ChEMBL 37 SQLite release,
  normalized the same way, scored against both the PubChem index and the ORD candidate
  names.
- Timings are single-process on an Apple M5 Pro laptop with 25 GB of RAM. The build
  spills about 18 GB of DuckDB scratch while grouping 118M synonyms; peak disk need is
  roughly 25 GB beyond the inputs.

## Findings

### 1. Acquisition and build cost

| step | wall time | output |
| --- | --- | --- |
| download `CID-SMILES.gz` | 72 s | 1,483,735,914 B (20.5 MB/s) |
| download `CID-Synonym-filtered.gz` | 50 s | 966,182,841 B |
| scan synonyms | 32 s | 117,641,528 rows |
| collapse to one CID per name | 25 s | 117,292,483 unique names |
| scan `CID-SMILES` | 37 s | 124,469,489 CIDs |
| join, sort, write Parquet | 79 s | 2,052,470,517 B (1.91 GiB) |
| write SQLite | 186 s | 10,942,590,976 B (10.19 GiB) |
| **total** | **8 min 2 s** | |

Every one of the 117,292,483 names joined to a structure — the synonym file names no CID
that `CID-SMILES` lacks. Ambiguity is negligible: **294,217 names (0.3%) match more than
one CID**, which is low because the *filtered* synonym list has already dropped names
PubChem judges inconsistent with the structure.

### 2. Coverage of the ORD name-only population

Against the 46,831 candidate names, split by what 2026-07-11 had already managed:

| prior outcome | names hit | rows hit |
| --- | --- | --- |
| unresolved | 3,028 / 45,155 (6.7%) | 45,707 / 254,336 (18.0%) |
| OPSIN | 399 / 1,663 (24.0%) | 8,285 / 14,006 (59.2%) |
| CIR | 9 / 13 (69.2%) | 49,294 / 59,847 (82.4%) |
| **total** | **3,436 / 46,831 (7.3%)** | **103,286 / 328,189 (31.5%)** |

The name rate is low and the row rate is high for the same reason 2026-07-11 found: the
long tail is singletons, and the head is a handful of very frequent solvents and
reagents. A 6.7% hit rate on names PubChem is being asked about for the first time is
also *the service's own rate* — the live probe of 400 of those names returned 6.2%, which
is the same number within sampling error.

Against the full 864,997 name-only rows:

| | names | rows | share |
| --- | --- | --- | --- |
| 2026-07-11 (curated + OPSIN) | 1,646 | 86,841 | 10.0% |
| local PubChem index | 3,436 | 103,286 | 11.9% |
| added by the index | 3,047 | 38,346 | 4.4% |
| **union** | **4,693** | **125,187** | **14.5%** |

### 3. The index and the service give the same answers

Across both probes — 700 live requests, 123 names where the service and the index both
answered:

| | misses probe (400) | top-names probe (300) |
| --- | --- | --- |
| both answered, same structure | 24 | 99 |
| both answered, **different** | **0** | **0** |
| API only | 1 | 2 |
| local only | 0 | 0 |
| neither | 375 | 199 |

Zero disagreements. This is the finding that makes the rest of the entry worth acting on:
the index is not a heuristic reimplementation of PubChem's name lookup, it is the same
mapping served from disk.

The live probe also fixes the baseline. Latency was **p50 177–190 ms, p95 240–293 ms**,
and across 700 requests at 3/second PubChem never throttled us — its
`X-Throttling-Control` header reported Green at ~20% of the request-count budget and 1%
of the request-time budget throughout. The hit rate was 6.2% on the unresolved tail and
**33.7% on the 300 highest-frequency names**, confirming that the value of a name lookup
is concentrated in the head of the distribution.

### 4. The only way the index differs from the service is normalization

All three names the service answered and the index missed were the same string with a
U+2032 PRIME instead of an apostrophe: `N,N′-carbonyldiimidazole`. PubChem's REST lookup
folds it; an index keyed on the lowercased string does not, because the bulk file spells
that synonym `n,n'-carbonyldiimidazole`.

Folding lookalike punctuation on the query side
([`normalize_gap.py`](../assets/2026-08-08-local-pubchem-name-lookup/normalize_gap.py) —
primes, curly quotes, the dash family, non-breaking and zero-width spaces) recovers
**57 names and 2,643 ORD rows**, taking coverage from 3,436 to 3,493 names. It is
query-side only: exactly **one** of the 117M index keys contains a foldable character, so
there is nothing to normalize on the data side.

Greek letters are deliberately left alone — `alpha` and `a` are not interchangeable in a
chemical name.

### 5. One artifact is enough, and it is the Parquet

The first cut looked like a clean split — SQLite for one name, Parquet for all of them:

| access | p50 | p95 | notes |
| --- | --- | --- | --- |
| PubChem PUG REST | 177 ms | 293 ms | plus a 10 s timeout budget per fallthrough |
| SQLite, first lookup | 0.81 ms | | cold page cache |
| SQLite, warm | **0.008 ms** | 0.30 ms | 10.2 GiB file, `WITHOUT ROWID` B-tree |
| SQLite, all 46,831 names in a loop | 2.00 s total | | 43 µs per name, mostly cold |
| DuckDB over Parquet, single name | 64 ms | 88 ms | scans a matching 1M-row group |
| DuckDB over Parquet, all 46,831 names | **0.74 s total** | | 16 µs per name |

A Parquet point lookup being *slower than calling PubChem* is an artifact of the row
group size, not of the format. The file is name-sorted, so a reader prunes to one row
group by its min/max statistics and then scans it; with 1M-row groups that is a million
strings to find one. Rewriting the slim index with **50k-row groups and a Bloom filter**
— 792 row groups instead of 41 — costs 1.5 MB (846.6 MB against 845.1 MB) and changes
the picture:

| reader | rg = 1M | rg = 50k |
| --- | --- | --- |
| DuckDB | 51 ms | **6.3 ms** |
| `pyarrow.dataset`, persistent handle | 42.7 ms | **6.3 ms** |
| `pyarrow.parquet.read_table`, per call | 43.9 ms | 8.8 ms |

At 6.3 ms the Parquet is **28× faster than the service it replaces**, which is the
comparison that matters — nobody is choosing between 8 µs and 6 ms, they are choosing
between either of those and a 177 ms network call with a 10 s timeout behind it.

Two things then settle it in the Parquet's favor:

- **Dependencies.** `resolvers.py` is a core ord-schema module, and DuckDB is not a core
  dependency — it lives in the optional `agent` extra, deliberately
  ([`pyproject.toml`](https://github.com/open-reaction-database/ord-schema/blob/main/pyproject.toml):
  *"parsing or validating a dataset needs neither"*). But **`pyarrow>=14` is core**, and
  pyarrow reads the tuned Parquet at the same 6.3 ms. So the Parquet is reachable from
  the core resolver with no new dependency, and so is SQLite (stdlib) — neither format
  wins on dependencies, but the Parquet no longer loses.
- **Bytes.** 806 MiB against 4.87 GiB, for the same content.

And the SQLite is *derivable*: writing it from the slim Parquet took **42 s** (finding
6). A caller that genuinely needs microsecond lookups can build it locally at install
time. Shipping a 4.87 GiB file to save 42 s of one-time work, for a latency nobody has
asked for, is redundancy rather than coverage.

### 6. Two-thirds of the index is machine identifiers

PubChem synonyms are mostly not names anyone types:

| class | names | share |
| --- | --- | --- |
| vendor / database accession (SCHEMBL, ZINC, AKOS, MFCD, DTXSID, …) | 68,813,550 | 58.7% |
| SMILES-looking string | 4,518,016 | 3.9% |
| CAS-like registry number | 4,311,663 | 3.7% |
| InChIKey | 3,382,130 | 2.9% |
| UNII-style 10-character code | 51,158 | 0.0% |
| **kept by a slim index** | **40,527,690** | **34.6%** |

Dropping them costs nothing: **zero** of the 46,831 ORD candidate names fall into any of
these classes. CAS numbers are kept deliberately — people do record them — but the vendor
accessions are the bulk of the file and no ORD compound is named by one.

| artifact | full | slim |
| --- | --- | --- |
| Parquet (ZSTD) | 1.91 GiB | **806 MiB** |
| SQLite | 10.19 GiB | **4.87 GiB** |

An 806 MiB Parquet is a shippable data package. The prefix patterns need care in exactly
one direction: an early version anchored on `zinc` rather than `zinc[0-9]` and dropped
`zinc chloride diethyl ether`, and `s[0-9]` would have dropped `s1p`. Anchor to a digit
wherever the letters alone could begin a real name.

### 7. The index reproduces PubChem's label collisions, 20,000× faster

Grading the 60 hits with the most ORD rows behind them
([`top_hits_reviewed.tsv`](../assets/2026-08-08-local-pubchem-name-lookup/top_hits_reviewed.tsv)):

| verdict | names | rows | share of reviewed rows |
| --- | --- | --- | --- |
| `ok` | 37 | 61,839 | 86.8% |
| `label` | 23 | 9,380 | 13.2% |

`ok` is the boring majority and it is genuinely good: `cuprous iodide`, `NH4OAc`,
`Pd(OAc)2`, `[Rh(cod)2]BF4`, `stannous chloride dihydrate`, `ceric ammonium nitrate` — the
inorganics and abbreviated reagents that OPSIN cannot parse and that a hand-written
dictionary would take a long afternoon to cover. This is the real prize.

`label` is where ORD's name field and PubChem's synonym table collide. ORD records
paper-local compound labels and functional-class words in the same field as real names;
PubChem has some depositor's specific structure filed under each of those strings:

| name | ORD rows | what the index returns |
| --- | --- | --- |
| `4A` | 1,245 | a benzothiazine (the name means 4Å molecular sieves) |
| `anhydride` | 1,004 | a nucleotide |
| `II` | 782 | a dipeptide |
| `dimethyl acetal` | 719 | 1,1-dimethoxyethane |
| `3A` | 691 | a rhodium phosphine complex |
| `imine` | 588 | a macrocyclic Schiff base |
| `thiol` | 301 | hydrogen sulfide |
| `Boc` | 262 | a peptide |

This is not a defect of building the lookup locally — the service returns the same thing.
What is new is the cost of being wrong: with no rate limit and no network, there is
nothing to stop a backfill from writing 9,380 wrong structures in a few seconds, and a wrong SMILES
identifier is worse than none, because it counts as structural and masks the compound from
every later resolution pass.

A length guard is tempting and only half-works: of the 23 label collisions, 9 are three
characters or fewer (3,904 rows), but so are two correct answers, `Mg` and `Si` (851
rows). The class words — `anhydride`, `acetal`, `imine`, `epoxide`, `sulfonamide`,
`diazonium`, `oxide` — need a stoplist, which is what 2026-07-11's junk filter already is
and where it should be extended. Punctuation folding pulls in a little of the same
trouble: it recovers `N,N′-carbonyldiimidazole` correctly, and also matches
`N,N′-dimethylacetamide` to N-methylpropanamide.

### 8. What the rate limit actually costs

At 3 requests/second, resolving the 46,831-name backlog online takes **4.3 hours**
(2.6 hours at PubChem's 5/second ceiling), and the probes suggest it would complete
without throttling. That is a real cost but a one-time one, and it is not the case for
building an index.

The case is the paths where a name is resolved on someone's request:
`ord_schema/agent/README.md` resolves a compiled query's named compounds through
`resolve_name` before binding parameters, and `ord-interface`'s NL query endpoint does
that per request behind a Redis cache. There, PubChem's 177 ms is a floor, a cold cache
plus a PubChem 503 costs a fallthrough to a CIR that has been down and an OPSIN that
refuses trivial names, and the user sees a failed query. Making that lookup a local 6 ms
call removes an external dependency from the request path entirely and makes the resolver
deterministic in tests and in CI.

### 9. OPSIN is also a network call, and it should not be

`_opsin_resolve` posts to `https://www.ebi.ac.uk/opsin/ws/`, one request per name. OPSIN
is a Java library; `py2opsin` runs the jar. Both shapes were measured
([`bench_opsin.py`](../assets/2026-08-08-local-pubchem-name-lookup/bench_opsin.py)):

| shape | time |
| --- | --- |
| all 46,831 names, one JVM | **2.3 s** (0.05 ms/name) |
| one name, one JVM | 230 ms (p50) |
| one name, EBI web service | ~200 ms |

So the win is entirely in batching. A JVM start costs more than the HTTP round trip it
replaces, which means `py2opsin` dropped in behind the current per-name interface would
make the interactive path *slower*. Getting the batch number needs either a persistent
JVM (JPype) or a resolver interface that takes a list of names.

The fidelity check turned up something more useful than the timing. Local OPSIN with
py2opsin's defaults resolves **1,222** of the candidate names; the EBI service resolved
**1,663**. The gap is one flag:

| py2opsin flags | hits | web-only | local-only |
| --- | --- | --- | --- |
| defaults | 1,222 | 459 | 18 |
| `allow_acid` | 1,250 | 459 | 46 |
| **`allow_radicals`** | **1,678** | **4** | 19 |
| `allow_bad_stereo` | 1,783 | 459 | 579 |
| all four | 2,280 | 4 | 621 |

`allow_radicals` reproduces the web service almost exactly — 4 web-only names out of
1,663, and **identical SMILES on every name both resolve**. So the EBI deployment runs
OPSIN with radicals allowed, and the 456 names it gains are substituents:

| name | ORD rows | web service returns |
| --- | --- | --- |
| `nitro` | 307 | `[N+](=O)[O-]` |
| `Boc` | 262 | `[C](=O)OC(C)(C)C` |
| `amino` | 192 | `[NH2]` |
| `carbonyl` | 178 | `[C]=O` |
| `bromo` | 144 | `[Br]` |
| `methyl` | 74 | `[CH3]` |

RDKit parses all of them, so `resolve_names` writes them onto compounds as structures.
**456 of the 1,663 OPSIN hits recorded in 2026-07-11 (27%, 3,793 rows) are substituent
fragments, not compounds** — a correction to that entry's numbers, and
[ord-schema#953](https://github.com/open-reaction-database/ord-schema/issues/953).

The useful consequence: running OPSIN locally with py2opsin's **defaults** is both faster
in batch and *more correct* than the service, because declining `methyl` is the right
answer.

### 10. A unified index over PubChem + CIR + ChEMBL does not assemble

The obvious next thought is to merge all three sources into one local table. Taking them
in turn:

**NCI/CADD CIR publishes no name index, and blocks us if we ask it enough times.** The
only bulk download the CADD group offers is the
[Open NCI Database](https://cactus.nci.nih.gov/download/nci/) — 266,151 records, Release
4, **May 2012**. CIR's actual resolving power comes from the CACTVS/CSLS aggregation
behind the service, which is not published, so there is nothing to merge.

The service is also not usable as a fallback, and this run pins down why. CIR answered
three hand-typed requests fine (`aspirin`, `TEA`, `palladium acetate`, ~0.2–0.5 s each).
A paced probe at 3 requests/second over 400 names the PubChem index missed then produced:

| outcome | count |
| --- | --- |
| `URLError` — TLS connection dropped | **368** |
| HTTP 500 (CIR's "not found") | 28 |
| HTTP 200 | 2 |
| HTTP 404 | 2 |

It answered about thirty requests and then began dropping the TLS handshake on every
subsequent one, and kept doing so afterwards for single hand-typed requests
(`curl` exit 35, `SSL: UNEXPECTED_EOF_WHILE_READING`). This is an IP-level block, and it
is reproducible at roughly 30 requests. [2026-07-11](2026-07-11-name-only-compounds.md)
recorded CIR as "down / blocking us (connection-level failures on every request)" —
**it was not down; we had tripped this.**

The two names CIR did resolve were `enols` → `OC=C` and `butanol-toluene` →
`CCCCO.Cc1ccccc1`, i.e. a class word and a solvent mixture. Combined with `TEA` →
triethanolamine, still wrong today, CIR's marginal contribution over the PubChem index on
ORD names is **0.5% of names, and both answers are ones we would want to reject.**

**PubChem already contains ChEMBL, and where it does not, the two disagree.** The first
half is a depositor relationship: PubChem's synonym table carries **2,892,861 `CHEMBL…`
accessions** against ChEMBL 37's ~2.5M compounds. Measuring it directly on the names
rather than the accessions — `molecule_synonyms` ∪ `molecule_dictionary.pref_name`,
joined to `compound_structures`, from the 5.4 GB ChEMBL 37 SQLite release:

| | |
| --- | --- |
| ChEMBL names with a structure | 107,635 |
| already in the PubChem index | **103,637 (96.3%)** |
| ORD candidate names ChEMBL resolves and PubChem cannot | **36 (387 rows)** |

36 names out of 46,831, and 387 rows out of 328,189 — **0.1%**. Most of them are the same
paper labels as before (`compound a`, `c5`, `9d`, `28a`, `18d`, `compound 16`); the
genuine additions are a handful of formulated and mineral names PubChem indexes
differently (`tween 20`, `tween 80`, `butylated hydroxytoluene`, `gypsum`, `kaolin`),
worth about 100 rows between them.

The second half is the real objection. Of the **130 ORD names both sources resolve, 44
(34%) return a different structure**:

| name | PubChem | ChEMBL |
| --- | --- | --- |
| `lime` | `O=[Ca]` | `[Ca+2].[O-2]` |
| `estrogen` | ethinylestradiol, no stereo | ethinylestradiol, full stereo |
| `hydrotalcite` | 12 waters | 4 waters |
| `lion` | a nucleoside | kaolin |

Some of these are representation differences (covalent against ionic CaO, stereo present
against absent) and some are flatly different compounds. Merging sources therefore does
not just add rows, it creates a conflict-resolution problem on a third of the overlap,
with no principled tiebreak available — and the disagreement rate is *higher* than the
0.1% of new coverage the merge buys. A union that is 96.3% redundant, 0.1% additive, and
34% contradictory on the remainder is not worth building.

**And the residual gap is not a coverage gap that a fourth database fixes.** Spot-checking
the highest-row misses against both the index and the live service — they agree exactly,
including on the misses:

| name | ORD rows | local index | live PubChem |
| --- | --- | --- | --- |
| `petroleum ether` | 13,740 | miss | 404 |
| `TEA` | 8,491 | miss | 404 |
| `polyphosphoric acid` | 1,744 | miss | 404 |
| `NaSO4` | 1,088 | miss | 404 |
| `xylenes` | 858 | miss | 404 |
| `N,N-dimethylaminopyridine` | 760 | miss | 404 |
| `DMAP` | — | `CN(C)C1=CC=NC=C1` | same |

What is left over is reagent abbreviations PubChem does not index (`TEA`), typos
(`NaSO4`), nonstandard spellings of names it does know (`N,N-dimethylaminopyridine`
against the `DMAP` it resolves fine), undefined mixtures (`petroleum ether`, `xylenes`),
and non-compounds (`steel`, `Si PCC`). ChEMBL is a narrower vocabulary than PubChem, not a
wider one — bioactive drug-like compounds with INN and trade names — so it addresses none
of these. **The missing tier is a curated ORD reagent dictionary, not a third database**,
which is the same conclusion 2026-07-11 reached from the other direction.

## Conclusions / next steps

**Build it, ship the slim Parquet, and insert it as a tier — do not delete anything.** The
resolver chain becomes: curated dictionary → local PubChem index → PubChem REST →
CIR → OPSIN. Each step earns its place:

1. **The curated dictionary goes first,** unchanged from 2026-07-11's conclusion. It is
   the only tier that gets `TEA`, `hexanes`, and `4A` right, and finding 7 shows the
   index will happily be wrong about all three classes of name it covers.
2. **The local index goes second,** with query-side punctuation folding (finding 4) and
   the 2026-07-11 junk filter extended with the functional-class stoplist from finding 7
   applied *before* lookup. It answers a third of the highest-frequency ORD names — 99 of
   the 300 probed, the same ones the service answers (finding 3) — in 6 ms, offline.
3. **The online resolvers stay as the fallback,** for names newer than the last dump and
   for anything the index misses. Keeping them costs nothing and removes the freshness
   objection.

Concretely:

- **Ship one artifact: the slim Parquet, 806 MiB, written with 50k-row groups and a Bloom
  filter** (finding 5), stamped with the dump date. Not the SQLite — it is 6× the bytes
  for a latency nobody in this codebase needs, and a caller who does need it can build it
  from the Parquet in 42 s. The natural home is alongside the ord-data HuggingFace mirror
  that already carries `views/` and `annotations/`
  ([2026-07-25](2026-07-25-derived-parquet-sidecars.md)) — same distribution, same
  citation, and `huggingface_hub` already knows how to fetch a single file. Rebuild
  quarterly; PubChem regenerates the source files with every dump, so a refresh is a
  re-download and a six-minute rerun, and there is no diff to reconcile.
- **Read it with `pyarrow`, not DuckDB, from `resolvers.py`.** pyarrow is already a core
  ord-schema dependency and is exactly as fast on this file; DuckDB is deliberately
  confined to the optional `agent` extra
  ([2026-07-25 scripts boundary](2026-07-25-ord-schema-scripts-boundary.md) is the entry
  about not making the library carry other people's dependencies). Batch consumers that
  already have DuckDB can join against the same file.
- **For the name-only backfill, gate on the dictionary, not on the index.** The union is
  14.5% of name-only rows against 10.0% today (finding 2) — worth having, but the extra
  4.4 points arrive mixed with the label collisions from finding 7, so the write-back
  wants the stoplist and a review of the head of the distribution, not a bulk apply.
- **Run OPSIN locally, but only if the resolver learns to batch** (finding 9). Keep
  py2opsin's defaults rather than matching the EBI service's `allow_radicals` — declining
  `methyl` is the correct answer, and it is the same class of guard the curated dictionary
  provides for PubChem.
- **Do not add sources; add a dictionary** (finding 10). CIR cannot be merged (no bulk
  index) or relied on (it blocks at ~30 requests), and ChEMBL is 96.3% redundant with a
  34% disagreement rate on the overlap. Effort that would go into a second source is
  better spent extending the 2026-07-11 curated dictionary down the frequency list, which
  is the only tier that covers what is actually missing.
- **Fix the three filed bugs:**
  [#952](https://github.com/open-reaction-database/ord-schema/issues/952),
  [#953](https://github.com/open-reaction-database/ord-schema/issues/953),
  [#954](https://github.com/open-reaction-database/ord-schema/issues/954). #953 is worth
  doing regardless of everything else here: it is writing radical fragments onto
  compounds today.

*Changes if:* PubChem starts throttling us at polite serial rates, or the interactive
resolve path grows past a cache's reach — either makes the index load-bearing rather than
an optimization, and justifies the ops cost of a refresh schedule. Conversely, if the NL
query cache turns out to absorb essentially all interactive lookups, the index's value
collapses back to the batch case, and the batch case is four hours of patience.

## References

- `ord_schema/resolvers.py` — the chain under discussion (`_pubchem_resolve`,
  `_cactus_resolve`, `_opsin_resolve`), and `ord_schema/agent/README.md` for the NL query
  path that resolves names before binding query parameters.
- Issues filed from this entry:
  [ord-schema#952](https://github.com/open-reaction-database/ord-schema/issues/952)
  (multi-CID PubChem responses),
  [#953](https://github.com/open-reaction-database/ord-schema/issues/953) (OPSIN
  substituent radicals),
  [#954](https://github.com/open-reaction-database/ord-schema/issues/954)
  (`IsomericSMILES` rename).
- Prior entries: [2026-07-11 name-only compounds](2026-07-11-name-only-compounds.md) (the
  inventory, the junk filter, and the curated dictionary this builds on),
  [2026-07-25 derived parquet sidecars](2026-07-25-derived-parquet-sidecars.md) (the
  HuggingFace distribution this would reuse),
  [2026-07-25 where ord-schema ends](2026-07-25-ord-schema-scripts-boundary.md) (why the
  library does not take on optional dependencies for one caller's benefit).
- PubChem bulk data:
  [`Compound/Extras`](https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/) and its
  [`README-Extras`](https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/README-Extras);
  [PUG REST usage policy](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) (5 requests/s,
  400/minute). Files used are the 2026-08-08 regeneration.
- Other sources considered: the NCI/CADD
  [Open NCI Database download page](https://cactus.nci.nih.gov/download/nci/) (Release 4,
  May 2012, 266,151 records — the only bulk file behind CIR), and
  [ChEMBL 37](https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/)
  (`chembl_37_sqlite.tar.gz`, 5.4 GB).
- [`py2opsin`](https://pypi.org/project/py2opsin/) 1.2.0, wrapping the
  [OPSIN](https://github.com/dan2097/opsin) jar.
- Scripts and data:
  [`assets/2026-08-08-local-pubchem-name-lookup/`](../assets/2026-08-08-local-pubchem-name-lookup/README.md).
