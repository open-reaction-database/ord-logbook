# Validation performance: every molecule is parsed twice, then again next reaction

- **Date:** 2026-08-02
- **Author:** Steven Kearnes
- **Status:** draft (profiling done; 2.86× in review, structural decisions recorded)
- **Tags:** performance, validation, ord-schema, ord-data, ci, rdkit, profiling

## Question

The `validate_parquet (uspto)` shard in ord-data's validation workflow runs for the
better part of an hour on a single file, and it is the long pole of every full-corpus
sweep. Where does that time actually go, and how much of it is avoidable?

## Summary

**It is duplicated work, not chemistry — and roughly 5.7× of the per-reaction cost is
recoverable without changing what validation checks.**

- Validation compute is **>97%** of the uspto shard: LFS fetch 77 s, environment setup
  6 s, `validate_dataset.py` **~75 min**. Parquet decode is **1%** of validation and
  cross-reference `observe` is **0.2%** — I/O and the dataset-level pass are not worth
  optimizing.
- Half the time is one call: **`Chem.MolFromInchi` is 51%** of `validate_message`.
  `dateutil.parser.parse` is 15%, `canonical_smiles` 11%.
- The cause is **the same string being parsed twice per reaction by two call sites that
  don't know about each other**, in two separate places with the identical shape:
  compound identifiers (validity check + consistency check) and DateTimes (tree walk +
  provenance ordering check). `MolFromInchi` takes **15,306 calls for 5,336 InChI
  identifiers**.
- On top of that, values repeat *across* reactions: **93%** of InChI lookups in a single
  1,000-reaction row group are repeats; one dataset hits **99.9%**.
- Memoizing by string — measured, not estimated — gives **2.06× → 3.64× → 5.74×** as the
  RDKit parse, canonicalization, and datetime caches are layered on.
- **The prototype's Mol cache is not shippable**: it hands the same mutable RDKit `Mol`
  to every caller. The production shape is to memoize the derived *string*.
- **A rewrite is not the answer.** ~73% of the time is already compiled C++ inside RDKit,
  and the distinct-molecule set does not saturate (~1.3 new per reaction, 32k reactions
  in), so the whole envelope for a faster validator is ~7–10× and nearly all of it is
  reachable in Python.
- The bigger structural lever is orthogonal to all of this: **the corpus is immutable and
  append-mostly, so most of what the weekly sweep validates has already been validated,
  unchanged, against the same library versions.** That, not a faster validator, is where
  an order of magnitude lives — but it is deferred, because a fast enough validator makes
  the machinery unnecessary.
- **Shipped so far: 2.86×** (1.785 → 0.625 ms/reaction), across
  [ord-schema#925](https://github.com/open-reaction-database/ord-schema/pull/925) and
  [#926](https://github.com/open-reaction-database/ord-schema/pull/926). Message-level
  deduplication was measured and **dropped** — it is 1.20× where memoization is 11×.

## Method

Profiled against the real corpus, not synthetic data:

- **Host:** M-series laptop, Python 3.11.15, ord-schema at `88a0cfd` (main), rdkit from
  the repo's locked resolution.
- **Data:** `data/11/ord_dataset-1158e351757f315b93cbcbe7bc55f38e.parquet` — the uspto
  grants file, **1,771,032 reactions in 1,772 row groups** (~73% of the 2.43M-reaction
  corpus), plus `e7830cd6…`, `488402f6…`, `5481550056…`, and `805ad863…` for contrast.
- **Unit of work:** exactly what `_validate_row_group` does — decode a row group with
  `parquet.iter_reactions`, then `validations.validate_message(reaction,
  raise_on_error=False)` and `state.observe(reaction)` per reaction. Decode is timed
  separately so it does not contaminate the validation numbers.
- **Tools:** `cProfile` sorted by `tottime`, plus `print_callers` to attribute the RDKit
  calls to their call sites; a memoization prototype that monkeypatches
  `Chem.MolFromInchi` / `MolFromSmiles` / `MolFromMolBlock`,
  `message_helpers._COMPOUND_IDENTIFIER_LOADERS`, `message_helpers.canonical_smiles`,
  and `validations.parser.parse` with `functools.lru_cache`, timing after each layer.
- **CI ground truth:** per-step timings from
  `gh api repos/…/actions/runs/30768225451/jobs`.

Scripts live in the session scratchpad (`profile_validation.py`, `measure_dupes.py`,
`who_calls.py`, `try_cache.py`); they are small enough to rebuild from the description
above and were not committed.

## Findings

### Where the time goes

Baseline **1.785 ms/reaction** on the uspto file:

| | share of validation |
|---|---|
| `Chem.MolFromInchi` | 51% |
| `dateutil.parser.parse` | 15% |
| `canonical_smiles` (`Chem.MolToCXSmiles`) | 11% |
| tree walk, `warnings` context managers, protobuf reflection | ~23% |

For scale, in the same units: parquet decode is **0.019 ms/reaction** and
`DatasetCrossRefState.observe` is **0.003 ms/reaction**. The dataset-level
cross-reference pass that [ord-schema#922](https://github.com/open-reaction-database/ord-schema/pull/922)
was careful to preserve costs 0.2% of the run — that decision was cheap, and it stays
cheap.

### The duplication

Two independent call sites parse each structural identifier, once each, per reaction:

```python
# validations.py:885 — validate_compound_identifier: is it parseable?
parse_func, identifier_type = {...}[message.type]
if parse_func(message.value) is None: ...

# message_helpers.py:407 — check_compound_identifiers: do the identifiers agree?
mol = _COMPOUND_IDENTIFIER_LOADERS[identifier.type](identifier.value)
smiles.add(canonical_smiles(mol))
```

`print_callers` confirms the split exactly: for 500 reactions, `MolFromInchi` is called
3,705 times from each of the two sites. Neither is wrong on its own; together they do
the work twice.

DateTimes have the same structure — `validate_date_time` (`validations.py:1247`) parses
every DateTime as the tree walk reaches it, and `validate_reaction_provenance`
(`validations.py:1270-1275`) parses `experiment_start`, `record_created`, and
`record_modified` again to compare them. Six `dateutil` parses per reaction.

### Identifier reuse across reactions

Within one 1,000-reaction row group of the uspto file:

| identifier | occurrences | distinct | reuse |
|---|---|---|---|
| NAME | 6,258 | 2,760 | 2.3× |
| SMILES | 5,336 | 2,160 | 2.5× |
| INCHI | 5,336 | 2,080 | 2.6× |

Combined with the 2× within-pass duplication, a cache keyed on the identifier string
sees a **93% hit rate** on `MolFromInchi` and **92.7%** on `MolFromSmiles` — and that is
within a single row group, the *worst* case for a per-worker cache.

### Measured speedup from memoization

| stage | ms/reaction | cumulative |
|---|---|---|
| baseline | 1.785 | — |
| + RDKit parse cache | 0.865 | 2.06× |
| + `canonical_smiles` cache | 0.491 | 3.64× |
| + `dateutil` cache | 0.311 | **5.74×** |

It generalizes, with the size set by how much the data repeats:

| dataset | identifiers | speedup (parse + canonical) | hit rate |
|---|---|---|---|
| `1158e351…` (uspto) | SMILES + InChI | **3.74×** | 93.0% |
| `805ad863…` | SMILES | 2.26× | 99.9% |
| `e7830cd6…` | SMILES | 1.67× | 88.0% |
| `5481550056…` | SMILES | 1.59× | 88.2% |
| `488402f6…` | SMILES | 1.58× | 88.2% |

Datasets carrying both SMILES and InChI gain most, because InChI parsing is the
expensive one and carrying both is exactly what triggers the consistency check.

### What is left afterwards

With all three caches on, the remaining 0.311 ms/reaction is the walk itself:
`validate_message` recurses over **~77 sub-messages per reaction**, each wrapped in its
own `warnings.catch_warnings()` (77,451 enter/exit pairs per 1,000 reactions).
`validate_reaction_smiles` is ~16% of that remainder. There is no further big single
win inside the current structure.

### CI ground truth

From the `validate_parquet (uspto)` job of run 30768225451:

| step | wall clock |
|---|---|
| Fetch LFS shard from GitHub (1.1 GB) | 77 s |
| Checkout + `setup-uv` + `uv sync` | 6 s |
| Validate parquet datasets | **~75 min** |

The local per-reaction cost extrapolates consistently with this once the runner's slower
cores and its 4 vCPU (≈2 physical) are accounted for. Two incidental notes: the new
lockfile-based setup ([ord-data#280](https://github.com/open-reaction-database/ord-data/pull/280))
installs the schema library in 6 s where the previous checkout-and-`pip install .` took
far longer, and the 77 s LFS fetch is a floor that no compute optimization touches.

That run also answered a standing question: it was the first full-corpus sweep against
`ord_schema` 0.8.0 rather than the v0.6.3 the workflow had pinned, and all eleven shards
passed. Nothing the older library had been letting through.

### How much of this is even Python? (or: would a rewrite help?)

The cache layers decompose the per-reaction cost by language, because each one removes a
known call:

| removed by | ms/reaction | implemented in |
|---|---|---|
| RDKit parse cache | 0.920 | C++ (`MolFromInchi`, IUPAC InChI library) |
| canonicalization cache | 0.374 | C++ (`MolToCXSmiles`) |
| dateutil cache | 0.180 | Python |
| remainder (tree walk, protobuf, warnings) | 0.311 | Python |

**~73% of validation is already compiled C++ inside RDKit.** A rewrite in another
language does not make `MolFromInchi` faster — InChI parsing is the IUPAC C library
whatever calls it, and no Rust cheminformatics stack approaches RDKit's coverage, so the
chemistry would come back over FFI regardless. Eliminating *all* the Python and keeping
RDKit bounds the win at **1.37×**.

The dedup ceiling is also lower than the 93% row-group hit rate suggests. Sampling 32
row groups spread across the whole uspto file:

| reactions | InChI occurrences | distinct | new distinct/reaction |
|---|---|---|---|
| 4,000 | 21,250 | 7,147 | 1.68 |
| 16,000 | 86,144 | 25,607 | 1.48 |
| 32,000 | 171,355 | 48,667 | 1.32 |

The distinct set **does not saturate** — new molecules keep arriving at ~1.3 per reaction
32k reactions in, and the rate is barely declining. The high in-window hit rate is
locality (shared solvents, reagents, catalysts), not corpus-wide redundancy; uspto
products are largely unique. Perfect dedup still parses on the order of 1.5–2M distinct
molecules at 0.116 ms each — roughly **4 minutes of irreducible native work** per full
pass of this file.

So the envelope for making the validator faster is about **7–10×** (53 min of
single-core work → ~9 min memoized → ~5–8 min at the dedup floor), and nearly all of it
is reachable in Python. That is the argument against a rewrite: it would be a large
change to correctness-critical code for the last ~1.4× of a shrinking remainder.

**The order-of-magnitude win is not in the validator at all — it is in not running it.**
A sweep over bytes that have not changed since the last sweep, against the same library
versions, is ~100% redundant work. That is item 1 below — a manifest plus a cache key
rather than a rewrite — and it is deferred rather than dropped: if the validator gets fast
enough, an O(corpus) sweep is affordable and the manifest buys nothing.

## Bigger structural changes — and what was decided

Six candidates were considered beyond the memoization. Two were done, one is deferred,
three are dropped. The verdicts are recorded here with the reasoning, so they do not get
re-litigated from scratch.

**1. Don't validate what hasn't changed. — DEFERRED.** Validation output is a pure
function of (file bytes, library versions). Every dataset file is an LFS object that
already has a sha256 oid, and the corpus is append-mostly: a weekly sweep re-validates
~2.4 GB that is byte-identical to last week's. Keying a manifest on
`(oid, ord_schema version, RDKit version)` and skipping files already recorded as passing
turns the weekly job from O(corpus) into O(changed). The RDKit version has to be in the
key, not just `ord_schema`'s — canonicalization output can change across RDKit releases,
so a toolchain bump would otherwise silently reuse stale passes.

Deferred because it may not be needed: if the validator gets fast enough, an O(corpus)
sweep is affordable and the manifest is machinery with nothing to buy. Revisit if the
full sweep is still uncomfortably long after the speedups land.

Whenever it is built, one thing needs writing down: the sweep's stated purpose is bit-rot
detection, and skipping files must not skip *verifying* them. It doesn't — git-lfs checks
the object hash on checkout, so "did the bytes rot" is answered by the oid, and re-running
the validator only ever answers "did the validator's opinion change", which the version
key captures. That is the part that looks unsafe and isn't.

**2. Validate distinct sub-messages, not occurrences. — DROPPED, measured.** The idea was
to hash each `Compound` and validate the distinct set once. It does not subsume the
identifier caches; it is far weaker. Compound-validation cost per reaction on the uspto
file:

| | every occurrence | distinct only | gain from dedup |
|---|---|---|---|
| memoization off | 1.112 ms | 0.928 ms | **1.20×** |
| memoization on | 0.100 ms | 0.077 ms | 1.31× |

Memoization alone takes that path 1.112 → 0.100 ms, an **11×**; hashing alone manages
1.20×. Two reasons. A `Compound` carries amount, role and `is_limiting`, so the same
solvent at a different amount is a *different message* — compounds repeat only **1.3×**
where identifier values repeat 2.6×. And hashing cannot touch the within-compound double
parse at all, since that happens on first sight of every distinct compound.

It is also worst where it would matter most. Compound reuse is 8.6× on `805ad863…` and
2.1× on `e7830cd6…`/`488402f6…`, but 1.3× on uspto — the file that is 73% of the corpus
and the whole CI long pole. On top of the memoization it is worth ~4% of total validation,
in exchange for a cache of serialized message bytes, the correctness burden of replaying
findings under re-anchored traces, and reconciling with `validate_message`'s documented
license to modify messages in place.

**3. Move canonicalization to write time. — DROPPED.** Storing a canonical SMILES in the
parquet at write time would let validation compare strings instead of building molecules.
It is not available: canonicalization output can change across RDKit versions, so a stored
value is only valid for the RDKit that wrote it, and validation would be comparing against
a stale derivation after any upgrade. (The same fact is why item 1's cache key must
include the RDKit version.) This does not affect the tier-1 sidecars in
[2026-07-25-derived-parquet-sidecars.md](2026-07-25-derived-parquet-sidecars.md), which
are derived views rather than a validation oracle.

**4. Scale the one file out across machines. — DROPPED.** `--shard I/N` would let several
matrix jobs split the uspto file. The complexity is not warranted for what it buys once
the per-reaction cost comes down, and it adds a second sharding mechanism next to the
existing row-group parallelism.
[ord-schema#922](https://github.com/open-reaction-database/ord-schema/pull/922) is closed.
The measurement it produced is worth keeping: the dataset-level cross-reference pass costs
~0.2% of a run, so it should stay unconditional wherever validation is restructured.

**5. Replace the warnings channel with return values. — DONE**
([ord-schema#926](https://github.com/open-reaction-database/ord-schema/pull/926)).
Findings now go to a list in a `ContextVar` instead of `warnings.warn` read back through
`catch_warnings`, removing ~77 context managers per reaction: 0.670 → 0.625 ms/reaction.
The original argument for it was that it unblocks (2), which is now dropped; it stands on
removing the overhead and on `catch_warnings` mutating global state and being documented
as not thread-safe.

**6. Tier the checks. — NOT NOW.** Splitting cheap structural checks from the RDKit and
dateutil work would let the weekly sweep run less. Better to have (1) than a policy that
quietly validates less.

## Conclusions / next steps

Landed or in review:

1. **Memoize by string** — [ord-schema#925](https://github.com/open-reaction-database/ord-schema/pull/925),
   **2.66×** (1.785 → 0.670 ms/reaction). Caches the derived string keyed on
   `(type, value)`, never the `Mol`, so nothing mutable is shared; the `sanitize=False`
   retry is a second cache consulted only after a failure. The `dateutil` cache is safe
   outright because `datetime` is immutable.
2. **Collect findings directly** —
   [ord-schema#926](https://github.com/open-reaction-database/ord-schema/pull/926),
   cumulative **2.86×**. Verified by dumping every finding for 1000 uspto reactions before
   and after: 3951 findings, byte-for-byte identical.
3. **Deterministic messages** —
   [ord-schema#927](https://github.com/open-reaction-database/ord-schema/pull/927). Found
   while verifying (2): `check_compound_identifiers` rendered a Python set, so the same
   code produced 314 differing lines across consecutive runs. Validation output that
   cannot be diffed across runs is a liability in its own right, and would have quietly
   undermined item 1 had that cache ever keyed on output rather than input.

Standing conclusions:

- Do **not** optimize parquet decode or the cross-reference pass; together they are ~1.2%
  of the run.
- Do **not** rewrite the validator in another language: ~73% of the time is already
  compiled C++ inside RDKit, which bounds a rewrite at 1.37×.
- Re-measure the full sweep once (1)–(3) are on `main`, and only then decide whether the
  deferred manifest is worth building.

## References

- [ord-data#280](https://github.com/open-reaction-database/ord-data/pull/280) — validation
  runs from the locked `ord_schema`; source of the CI step timings here. Merged, with all
  eleven shards green under 0.8.0.
- [ord-schema#925](https://github.com/open-reaction-database/ord-schema/pull/925) —
  memoize identifier parsing (2.66×).
- [ord-schema#926](https://github.com/open-reaction-database/ord-schema/pull/926) —
  collect findings directly instead of through `warnings` (cumulative 2.86×).
- [ord-schema#927](https://github.com/open-reaction-database/ord-schema/pull/927) —
  deterministic ordering in the inconsistent-identifiers message.
- [ord-schema#922](https://github.com/open-reaction-database/ord-schema/pull/922) —
  `--shard I/N` for `validate_dataset.py`. **Closed**; kept for the measurement showing
  the dataset-level cross-reference pass is nearly free.
- [ord-schema#923](https://github.com/open-reaction-database/ord-schema/pull/923) —
  unreadable files reported against the file, found while doing this work.
- Prior entry: [2026-06-30-ingest-derivation-performance.md](2026-06-30-ingest-derivation-performance.md)
  — same corpus, same shape of finding (per-row work that should be set-based).
- Prior entry: [2026-07-25-derived-parquet-sidecars.md](2026-07-25-derived-parquet-sidecars.md)
  — where write-time canonicalization belongs.
