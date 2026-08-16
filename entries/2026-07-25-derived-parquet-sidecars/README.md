# Derived parquet sidecars for agent-accessible ORD

- **Date:** 2026-07-25
- **Author:** Steven Kearnes
- **Status:** draft (design settled; tier 1 implemented in ord-schema#914, not merged)
- **Tags:** ord-data, ord-schema, parquet, derived, agents, huggingface, duckdb, design,
  data-contracts

## Question

ORD is hard for an agent to use. What is the cheapest change that fixes the largest
part of that, and what does the design have to look like given the shape of the corpus
we actually have?

**Scope:** parquet only. Legacy `.pb.gz` is deprecated (`155261c`) and out of scope
entirely — no sidecars are derived for it, now or later. Coverage is defined over the
parquet corpus, so the 550 `.pb.gz`-only datasets are not a coverage gap; they arrive
when the parquet migration delivers them.

## Summary

There are **two independent reasons** ORD resists agent use, and they need different
fixes:

1. **The query surface is narrow.** `ord-interface/api/queries.py` exposes seven
   predicates: `dataset_id`, `reaction_id`, reaction SMARTS, conversion range, yield
   range, DOI, and component (INPUT/OUTPUT × EXACT/SIMILAR/SUBSTRUCTURE/SMARTS). The
   `ord.*` schema decomposes every proto message into its own table, so
   `ReactionConditions` (temperature, pressure, stirring, illumination,
   electrochemistry, flow, pH), vessel, workup, analyses, and provenance are all
   *indexed and unreachable*. `nl_query.py` inherits exactly this ceiling, since it only
   ever emits `QueryParams`.
2. **The bulk-data path has no pushdown.** `ord_schema/parquet.py` writes two columns —
   `reaction_id` (string) and `reaction` (serialized wire-format bytes) — with `Dataset`
   scalars in the footer KV metadata under `ord.*` keys. That supports random access by
   row group and nothing else. Anyone asking "yield > 70%" over the Hugging Face mirror
   must deserialize every proto.

**The second is the higher-value target and this entry covers it**: it helps everyone
who will never run our Postgres, and it needs no API changes.

The design is **parquet sidecars** — flat scalar columns beside each dataset — split
into two tiers. The split is **by contract, not by cost** (finding 1): tier 1 is
reproducible from the source protos alone with pinned open tooling, so CI can rebuild it
at will; tier 2 is not, because it needs a model, weights, or an external service, so it
must be produced out of band and can never run in a GitHub Actions job. Tier 1 needs
only pyarrow, protobuf, and rdkit — **no Postgres, no ORM rebuild** — which is what
makes it affordable.

Getting that line right is the load-bearing part of the design. "Cheap tier / expensive
tier" was the original framing and it would not have survived the second use case: cost
is a symptom, reproducibility is the cause, and it is reproducibility that determines
who writes the artifact, whether staleness is a bug, and whether coverage must be total.
Calling tier 1 "derived" is itself a misnomer — it restates what the protos already say
— which is why the published prefix is `views/`, not `derived/` (D6).

**v1 is tier 1 only, including per-component SMILES, published to Hugging Face and never
committed to git.** The three parts of that:

1. **Labels are out of v1.** Dropping `reaction_class`/`reaction_name` removes rxnmapper
   and torch from the pipeline entirely and decouples v1 from GPU provisioning. Tier 1
   by itself already answers most agent queries the current API cannot. The layout still
   has to leave room for labels and whatever follows them — embeddings, atom maps,
   retrosynthetic routes — which findings 2 and 2b reserve.
2. **Per-component SMILES ship.** They are the one column set that reproduces
   `ReactionComponentQuery` — the most-used existing predicate — which a reaction SMILES
   split on `>` cannot, because it loses role information and, for generated SMILES,
   silently drops components lacking structural identifiers.
3. **Sidecars are HF-only, in the existing `ord-data` repo.** A full tier-1 derivation
   was built and measured for this entry: **333.9 MB, or 26.6% of the source
   parquet corpus.** That is far too large for an append-only LFS store whose defining
   event is *wholesale invalidation on every derivation-version bump*. This reverses the
   position originally taken here; see finding 6. Keeping it in the same HF repo as the
   source restores commit-level pairing between them and lets the derived columns become
   the Data Studio default (D5).

The measurement also produced a simplification worth stating on its own: **the whole
corpus derives in 9.7 minutes single-process.** Nothing about this pipeline is expensive
enough to need the caching and part-directory machinery earlier drafts designed around
it — findings 3 and 4 are rewritten accordingly, and finding 9 drops the second
published artifact entirely. That in turn removes the second consumer for native `data/`
sharding.

Every decision is settled. See [the decision log](#conclusions--next-steps).

## Method

Corpus facts were measured against `ord-data` `main` at `e017725`, first on 2026-07-25
and re-measured on 2026-07-30 against the same commit, so the two runs below see a
byte-identical corpus. API and serialization claims were read from `ord-schema` at
`67a63c7` and the current `ord-interface` `main`.

Sizes here are decimal — MB is 10⁶ bytes, GB is 10⁹. Earlier revisions of this entry
reported binary units under the same labels, which is why figures may read ~5% lower in
the git history than they do now for identical files.

The sidecar cost in finding 6 is a real derivation, not an estimate. A tier-1 transform
was run over all 53 parquet datasets — script, per-dataset results, and a reproduction
guide in
[`ASSETS.md`](ASSETS.md)
— reading `parquet.iter_reactions` → flat columns, written with the same zstd codec the
source uses.

Two runs stand behind the numbers here, and they differ enough to name separately:

- **The scoping run** ([`derive_facts.py`](derive_facts.py)) derived all 52 non-USPTO
  datasets in full and sampled USPTO at 200 evenly-spaced row groups (200,000 of
  1,771,032 rows, 11.3%) — spaced rather than a leading prefix, since its row groups are
  in source order. It read component SMILES straight out of `SMILES` identifier values
  without invoking RDKit, and took reaction SMILES from a stored `REACTION_SMILES`
  identifier or `get_reaction_smiles(generate_if_missing=True)`.
- **The shipped run** is `ord_schema.views.write_view` at
  [`ord-schema#914`](https://github.com/open-reaction-database/ord-schema/pull/914)
  `9925c1c`, over all 53 datasets with no sampling. It canonicalizes every component
  through RDKit, prefers a stored `REACTION_CXSMILES` over `REACTION_SMILES`, and falls
  back to deriving a component's SMILES from MOLBLOCK or InChI.

Wall-clock was recorded alongside bytes, single-process on a laptop, and turned out to
matter more than the byte figures for the design:

| | rows | wall-clock | rate |
| --- | --- | --- | --- |
| 52 non-USPTO datasets | 657,259 | 209.0 s | 3,144 rxn/s |
| `uspto-grants` | 1,771,032 | 373.8 s | 4,738 rxn/s |
| **whole corpus** | **2,428,291** | **9.7 min** | 4,166 rxn/s |

The scoping run reported 1.8 minutes for the same corpus. Most of that gap was an
extrapolation error rather than a change in the work: USPTO's 31.9 s was the wall-clock
for the 200,000-row *sample*, and it went into the table against the full 1,771,032-row
count, which also produced the ~55,000 rxn/s figure. Extrapolated the way the byte
figures were, the scoping run's corpus time was **6.0 minutes**. The remaining 6.0 → 9.7
is real added work: a per-component RDKit parse and canonical write, partly offset by
USPTO no longer regenerating reaction SMILES it had stored all along (see finding 8).

Rate tracks component count, not row count. Across the six datasets big enough for the
figure to mean anything (39k rows and up, ~96% of the corpus) it spans 1,039 rxn/s on
Cernak C–N HTE to 5,054 rxn/s on a reaction-SMILES-only dataset — HTE reactions carry a
dozen or more components (solvents, catalysts, ligands, standards) and each one costs an
RDKit canonicalization, while USPTO reactions carry few. Below that size fixed costs
dominate and the rate says more about startup than about chemistry.

The corpus shape drives every decision below:

| fact | value |
| --- | --- |
| files under `data/` | 603, across 227 shard directories |
| legacy `.pb.gz` | 550 |
| `.parquet` | 53 |
| largest dataset | `ord_dataset-1158e351757f315b93cbcbe7bc55f38e` (USPTO grants, ~1.7M reactions, un-sharded) |
| HF mirror `main` | 2.44 GB, parquet format tag, live Data Studio view |

So: **one enormous file plus six hundred small ones.** Per-dataset incrementality is
nearly free for the six hundred and catastrophic for the one. USPTO is already
special-cased in the `validate_parquet` matrix in `validation.yml` for exactly this
reason.

## Findings

### 1. Two tiers, split by contract — not by cost

The original split was "cheap tier / expensive tier," which is a symptom rather than a
cause and would not have survived contact with the second use case. The durable line is
**reproducibility**:

> A tier-1 artifact is reproducible from the source protos alone, deterministically,
> with pinned open tooling (`ord-schema` + RDKit), **and it is policy-free** — no
> column encodes a threshold, cutoff, or classification that a reasonable consumer
> might set differently. A tier-2 artifact fails the first clause: it requires a model,
> weights, an external service, or a judgment that is not in the repository.

The policy-free clause is the one that is easy to lose, because a column can be
perfectly reproducible and still be wrong for tier 1. `is_negative_result` was in the
design until D2 removed it: given a threshold it is deterministic, so it passes the
reproducibility test — but the threshold is a scientific judgment nobody agreed on, and
publishing one silently imposes it on every consumer. If a column's value depends on a
parameter someone had to *choose*, that parameter belongs in the consumer's query, not
in the artifact. The same test would reject `is_high_yielding`, `temperature_category`,
and anything else that buckets a continuous measurement.

Cost falls out of the first clause rather than defining it, and so does everything
operationally important:

| | **tier 1** — restatement | **tier 2** — genuine derivation |
| --- | --- | --- |
| contents | reaction SMILES, per-component input/output SMILES, yield, conversion, temperature and pressure setpoints, reaction time, DOI, patent — [column by column below](#the-shipped-tier-1-columns-and-how-much-of-the-corpus-fills-them) | `reaction_class`, `reaction_name`, later: embeddings, atom maps, retrosynthetic routes |
| adds information? | no — a re-projection of what the protos already say | **yes** — an assertion *about* a reaction |
| reproducible offline? | yes, by anyone with `pip install ord-schema` | no — needs weights/GPU/service |
| if it disagrees with source | **it is wrong**; source is authoritative | cannot disagree; it says something source does not |
| staleness | a bug | normal and expected |
| coverage | must be total over parquet datasets | partial by nature |
| producer | CI, on every merge | out of band, whoever holds the GPU |
| v1? | **yes** | no |

The generated reaction SMILES is the useful edge case: it is *computed*, not literally
present in the proto, yet it is tier 1 because
`message_helpers.get_reaction_smiles(generate_if_missing=True)` is deterministic and
reproducible by anyone. Conversely, transformer atom mapping *looks* like normalization
— "just add atom maps to a SMILES" — but is a model prediction, so it is tier 2. The
test is not the shape of the output; it is whether the repo plus pinned open tooling can
regenerate it.

#### The shipped tier-1 columns, and how much of the corpus fills them

Each column names exactly one source field. The schema offers several plausible
readings of most of these — six `Time`-typed fields alone — so the column name has to
say which one, or a consumer will guess wrong. Coverage is over all 2,428,291 rows of
all 53 parquet datasets:

| column | populated | rows | datasets | source field |
| --- | ---: | ---: | ---: | --- |
| `reaction_id` | 100% | 2,428,291 | 53/53 | `Reaction.reaction_id` |
| `input_smiles` | 100% | 2,428,291 | 53/53 | per component, mean 4.75 per reaction |
| `reaction_smiles` | 100% | 2,428,290 | 53/53 | stored `REACTION_CXSMILES`/`REACTION_SMILES`, else generated |
| `output_smiles` | 100% | 2,428,068 | 53/53 | per component, mean 1.07 per reaction |
| `doi` | 97.9% | 2,377,486 | 43/53 | `Reaction.provenance.doi` |
| `patent` | 72.9% | 1,771,032 | 1/53 | `Reaction.provenance.patent` |
| `yield_percent` | 45.0% | 1,093,772 | 36/53 | largest `YIELD` `ProductMeasurement` of outcome 0 |
| `reaction_time_seconds` | 43.3% | 1,052,017 | 49/53 | `ReactionOutcome.reaction_time` |
| `temperature_kelvin` | 25.0% | 607,307 | 45/53 | `conditions.temperature.setpoint` |
| `pressure_kilopascals` | 0.3% | 7,026 | 3/53 | `conditions.pressure.setpoint` |
| `conversion_percent` | 0.2% | 4,225 | 6/53 | `ReactionOutcome.conversion` |

Two things follow. **Row coverage and dataset coverage disagree, and dataset coverage
is the one that matters for a view.** `yield_percent` leads on rows but appears in only
36 of 53 datasets, while `reaction_time_seconds` and `temperature_kelvin` appear in 49
and 45 — the conditions columns are the most *broadly* applicable in the artifact even
though fewer rows carry them. `patent` inverts this completely: 72.9% of rows, one
dataset, because USPTO is 73% of the corpus.

**Two columns are near-empty**: `pressure_kilopascals` (3 datasets) and
`conversion_percent` (6). Their cost is not the argument for keeping or cutting them —
an all-null column measures 762 KB across the corpus, so both together are under 1 MB
against a 476 MB artifact. The argument is contract surface: a column that is null for
99.7% of the corpus teaches a consumer to expect nulls everywhere.

Naming carries real weight here, because the ORD schema has six `Time`-typed fields —
`ReactionOutcome.reaction_time`, `ReactionInput.addition_time`,
`ReactionInput.addition_duration`, `ReactionWorkup.duration`,
`ReactionObservation.time`, and `ProductMeasurement.retention_time`. A column called
`time_seconds` sitting next to `temperature_kelvin` reads as a *conditions* field, which
it is not. It is the outcome's reaction time, and the column is named
`reaction_time_seconds` so that it cannot be read any other way. The same reasoning
keeps `setpoint` visible in the description of the temperature and pressure columns:
they are what the experiment was *asked* to hold, not what it achieved.

Two boundary cases the rule already answers: anything needing a **network service** (DOI
→ Crossref metadata, name resolution via PubChem) is tier 2, because a remote service is
not reproducible offline even when it is cheap and deterministic-looking. And the
existing label semantics confirm the staleness column above —
`orm/derived_mappers.ReactionClasses` treats row presence as "classification was
attempted," with NULL class/name meaning Rxn-INSIGHT could not assign one, so a missing
label row is already a normal state rather than a merge blocker.

**v1 ships tier 1 only.** Tier 2 is not built here, but the layout and write path below
must leave room for it, because the whole point of the split is that tier 2 can never
run in a GitHub Actions job.

### 2. Two prefixes, one per tier, both mirroring `data/`

```text
data/xx/ord_dataset-<id>.parquet                     source of truth (git + HF)
views/xx/ord_dataset-<id>.parquet                    tier 1, CI-written, HF only
annotations/<producer>/xx/ord_dataset-<id>.parquet   tier 2, out of band, HF only
```

`views/` is tier 1 — see D6 for why, and for the view definition the dataset card has to
carry. It mirrors `data/` one-for-one, and finding 9 establishes it
is the *only* tier-1 artifact: there is no second, compacted rendition.

**Why a separate prefix rather than co-locating in `data/`.** Adjacency is appealing —
"sidecar" implies it — but `data/**` is not just a location, it is a contract meaning
*in git, LFS-tracked, source of truth*, and five pieces of tooling already key on that
prefix:

| tooling | keyed on | breaks if views co-locate |
| --- | --- | --- |
| `.gitattributes` | `data/**/*.parquet filter=lfs` | a stray commit silently makes a view an LFS object — the exact outcome finding 6 forbids |
| `upload_to_huggingface.py` | `MIRROR_PATHSPECS = ("data/**", …)` | HF `data/` diverges from git `data/`, so the reconciliation hazard in finding 2b becomes likely rather than latent |
| `download_from_huggingface.py` | `DEFAULT_ALLOW_PATTERNS = ["data/**"]` | every source-only download silently grows by 26.6% |
| `validation.yml` | `--input="data/*/*.parquet"` | views get fed to a validator expecting Dataset protos, needing a negative carve-out in a regex that already carries one |
| `build_configs` | `glob("data/*/*.parquet")`, one config per file | views become bogus `ord_dataset-<id>` configs with a mismatched schema |

The submission guard (finding 7) is the sharpest case. With a separate prefix it is
"reject any PR touching `views/**`" — a path rule that cannot be got wrong. Co-located,
it becomes filename-suffix discrimination inside a directory contributors legitimately
write to. Tier 2 settles it anyway: `annotations/<producer>/` needs its own namespace
regardless, so co-locating tier 1 would split the two tiers across incompatible layout
conventions for no gain.

The locality that co-location buys is recoverable for free, because the paths are
identical after the prefix: `data/11/ord_dataset-X.parquet` ↔
`views/11/ord_dataset-X.parquet` is a one-token substitution.

`annotations/` is the tier-2 namespace, subdivided **by producer** (e.g.
`annotations/rxn-insight/`) so that adding embeddings later is a new directory rather
than a rewrite of the labels file. Independent producers must not share a file.

Common to both:

- The nine-way shard globs in `validation.yml` (`data/[0-4][0-4]`, …) are deliberately
  written to be valid both as a `validate_dataset.py` regex and as an LFS path glob.
  They apply to either prefix unchanged.
- Deletion is trivial: dataset removed → sidecar removed. No manifest to reconcile.
- Provenance is local — each file's footer carries its own stamps, so staleness is a
  per-file property checkable with a footer read, not a global invariant.
- **`reaction_id` is the join key**, never row position. That is what lets a consumer
  join tiers in DuckDB with no registry, and what lets tier 1 be regenerated freely
  without invalidating tier-2 files that reference it.

Where they differ is the footer. Tier 1 stamps source `dataset_id`, source md5,
ord-schema version, and derivation version — everything needed to answer "is this
current." Tier 2 needs all of that **plus producer identity**: model name, model
version, weights hash, and a run timestamp, because "what produced this and can I
reproduce it" is a question the repo cannot answer on its own. Deciding tier-2 stamps is
not v1 work, but the tier-1 stamp set should not be designed as though it were the only
one.

### 2b. Out-of-band writers need a path CI cannot clobber

Tier 2's defining constraint is that its producer is not the CI job. A GPU run, a
one-off backfill, or a collaborator's batch job uploads directly to Hugging Face.
Three consequences:

- **CI must never delete or rewrite `annotations/**`.** The hazard is already latent:
  `upload_to_huggingface.py` issues `CommitOperationDelete` only for paths deleted in
  the git diff, so today nothing touches it — but any future "make HF match git"
  reconciliation would wipe every tier-2 artifact, and unlike tier 1 those cannot be
  regenerated from the repo. This needs to be an explicit, commented invariant, not an
  accident of the current implementation.
- **Tier 1 regeneration must not invalidate tier 2.** Guaranteed by the `reaction_id`
  join key: re-deriving tier 1 changes bytes, not identities.
- **Publishing tier 2 needs a separate, authenticated entry point** — a documented
  script or workflow that takes an already-computed artifact and commits it to the
  mirror, distinct from the mirror job's derive-and-upload path.

### 3. Sidecars need no part directories — one file per dataset, including USPTO

An earlier draft gave large datasets a part directory
(`derived/11/ord_dataset-1158e351.../part-NNNNN.parquet`) so an edit touching 200 USPTO
reactions would rederive 200 rows instead of 1.7M. Two measurements retire that idea:

- **Off git, a rewrite costs nothing permanent.** The part scheme existed to shrink the
  unit of rewrite because every rewrite minted an immortal LFS object (finding 6). On
  Hugging Face a rewrite is an upload, and the storage backend's content-defined
  chunking dedupes the unchanged remainder.
- **A full rederivation of USPTO takes ~32 seconds.** At that cost there is nothing to
  optimize. Rewriting 1.7M rows to fix 200 of them is not a problem worth a directory
  layout.

So one sidecar file per dataset, at every size. This also removes the second consumer
that justified building native intra-dataset sharding for `data/` — see
[2026-07-25 native sharding within a dataset ID](../2026-07-25-native-sharding-in-data/README.md),
whose D1 turns on exactly this dependency.

### 4. Incrementality is an I/O optimization, not a compute one

Mirroring the existing `ord.*` KV convention in `parquet.py`, each sidecar stamps:
source `dataset_id`, source md5, ord-schema version, derivation version.
`parquet.streaming_md5` returns `(md5, num_reactions)` and is deliberately decoupled
from writer settings (row-group size, compression), so the same logical content
rewritten still hashes the same.

The original reasoning made those stamps a *cache key* to avoid expensive rederivation.
The measurement removes that motive: the whole corpus derives in **9.7 minutes**
single-process. Nothing here is expensive enough to cache — and note the conclusion is
insensitive to the number, since the alternative is a cache whose correctness has to be
defended on every schema change.

What is still expensive is **fetching the source**. A full rebuild needs all 1.26 GB of
source parquet pulled from GitHub LFS, whereas the mirror job today pulls only the
objects a commit actually changed. So still derive only what changed — for bandwidth,
not for CPU — and keep the stamps for what they are genuinely good at: **verifying** a
published sidecar against its source, rather than deciding whether to skip work.

The corollary is that bumping the *derivation version* stops being frightening. Finding
4 previously demanded a `workflow_dispatch` full rebuild carefully insulated from
routine merges, lest one refactor turn a data merge into a 1.7M-reaction job. At ten
minutes of compute plus a one-time full-corpus pull, a whole-corpus rebuild is a routine
operation — comfortably inside a CI job, and cheap enough that rebuilding is the obvious
response to any doubt about a published view.

### 5. The SMILES→class cache is corpus-wide, not a sidecar *(tier 2; post-v1)*

This is tier-2 infrastructure and ships with the labels artifact, not with v1. Recorded
here so the eventual design does not relitigate it.

Rxn-INSIGHT classifies a *reaction SMILES*, so cache on `smiles_hash → (class, name)` —
the same "deduplicate where the payload is expensive" principle the ORM README states
for `rdkit.reactions`. New submissions overlap heavily with chemistry already in USPTO,
so most new reactions hit the cache for free and only novel SMILES pay the transformer.
Steady-state cost then scales with novel chemistry rather than commit volume.

Making this per-dataset would destroy the deduplication that makes it affordable. It is
a third artifact with its own lifecycle.

### 6. Sidecars do not belong in git — the measurement settles it

An earlier draft of this entry put sidecars in git, reasoning that per-dataset files
localize churn better than a whole-corpus file. That compared two *git* options and
never asked whether a regenerable artifact belongs in an append-only store at all. The
measured cost says it does not.

Facts-tier derivation, actually run over the shipped column set — per-component SMILES
included (see Method):

| dataset | rows | source | sidecar | % of source |
| --- | --- | --- | --- | --- |
| `1158e351…` uspto-grants *(sampled)* | 1,771,032 | 1061.2 MB | 231.6 MB | **21.8** |
| `e7830cd6…` C8SC04228D train | 409,035 | 104.6 MB | 73.2 MB | **69.9** |
| `488402f6…` C8SC04228D test | 40,000 | 10.2 MB | 7.1 MB | 70.0 |
| `47eaacc4…` amide coupling 47k | 47,015 | 8.2 MB | 3.0 MB | 37.2 |
| `54815500…` C8SC04228D validation | 30,000 | 7.6 MB | 5.3 MB | 69.8 |
| `805ad863…` Cernak C–N HTE | 50,688 | 5.0 MB | 1.9 MB | 37.4 |
| **corpus (53 datasets)** | **2,428,291** | **1.257 GB** | **333.9 MB** | **26.6** |

Per-component SMILES account for 75.5 MB of that (+31% over the same columns without
them). They ship regardless — see D2 — so 333.9 MB is the number the location decision
has to absorb.

The scoping run's extrapolation held up. It put the corpus at 26.8% of source against a
measured 26.6%, and its 52 exact non-USPTO datasets came to 93.7 MB then and 93.7 MB
now — USPTO's 11.3% sample predicted the other 88.7% to within a percent. Sizes were the
one thing sampling estimated well; wall-clock it got wrong by 5× (see Method).

Three things fall out:

- **26.6% of the corpus is not a rounding error.** Against a repo whose HEAD is 2.43 GB
  of LFS objects and whose history already holds 5.88 GB across 1,235 objects, the
  initial sidecar commit adds ~334 MB — and **every derivation-version bump rewrites all
  of it.** Finding 4 already establishes that such a bump invalidates the whole corpus.
  In git that is ~334 MB of permanently unreachable LFS objects per bump: **14% of the
  live corpus for one bump, ~41% after three.** LFS has no delta encoding and
  `git lfs prune` is local-only, so nothing reclaims it.
- **The ratio is wildly non-uniform, so no threshold rescues it.** USPTO derives to
  21.8% because its protos are fat with provenance and atom-mapped SMILES; the
  C8SC04228D datasets are *only* reaction SMILES, so their sidecars are **70% of
  source**. "Small datasets in git, big ones on HF" would put the worst ratios in git.
- **Derived data is reproducible by construction.** Staleness is already answerable from
  the footer stamps (source md5 + ord-schema version + derivation version) without git,
  and partial coverage is already declared a normal state. Git buys atomic
  (source, derived) pairing by commit — a convenience the stamps replace.

The asymmetry decides it: **starting HF-only and later moving into git is easy; the
reverse leaves the bytes in history forever.** Take the reversible direction.

So both tiers are HF-only, and tier 1 regenerates on every merge to main — finding 4
establishes that derivation is cheap enough for that, and finding 9 establishes there is
only one artifact to regenerate.

**Where derivation runs:** inside the existing `huggingface_mirror.yml` job. It already
runs on push to main, already points LFS reads at GitHub and fetches exactly the objects
a commit changed, and already holds the `HF_TOKEN`. Deriving there and adding the
sidecars to the same mirror commit reuses all of it and keeps source and derived content
in one atomic HF commit.

**The cost of leaving git**, stated plainly: the HF mirror is currently a pure function
of git history — `upload_to_huggingface.py` diffs `MIRROR_PATHSPECS` and mirrors the
result. HF-only sidecars break that invariant, replacing one mechanism with two
(diff-then-mirror for `data/`, derive-then-upload for the tier-1 prefix). That is the
real price and it is worth paying. See finding 2b for the matching hazard on the tier-2
side, which is worse because those artifacts cannot be regenerated from the repo.

Flat scalar columns are exactly what the Data Studio viewer heuristics want either way,
so the published sidecars get a browsable preview for free.

### 7. Sidecars are never hand-written — and the existing guard has a gap

`check_file_types` in `submission.yml` passes anything matching
`\.(pb(txt)?(.gz)?|parquet)$`, so a contributor could submit a derived file today and
nothing would stop them. Keeping sidecars out of git makes this simpler, not moot: the
guard becomes "reject any derived-tier path in a PR" — an absolute rule rather than a
provenance check, because no legitimate commit ever adds one, in either tier.

Note the gap found while checking this: that job is fenced behind
`if: github.event.pull_request.head.repo.fork`, so it only runs on fork PRs. A
guard placed there inherits the same blind spot for branch PRs from maintainers. Either
lift the guard out of the fork condition or accept that maintainer-authored edits to
those paths are unchecked.

### 8. Generation is the common case per dataset, and a rounding error per reaction

**44 of 52** non-USPTO datasets store no reaction identifier at all, so
`get_reaction_smiles(generate_if_missing=True)` is the main path *by dataset*. Those 44
hold 90,000 rows between them. Counted by reaction, the picture inverts:

| | reactions | share |
| --- | ---: | ---: |
| stored `REACTION_CXSMILES` (all USPTO) | 1,771,032 | 72.9% |
| stored `REACTION_SMILES` (8 non-USPTO datasets) | 567,259 | 23.4% |
| **generated** | **90,000** | **3.7%** |

The scoping run reported USPTO as 100% generated. It is 100% *stored*: every USPTO
reaction carries a `REACTION_CXSMILES` identifier, and `derive_facts.py` matched only
`REACTION_SMILES`, so it regenerated 1.77M reaction SMILES the corpus already had. That
one missed enum value is also why USPTO looked cheap.

RDKit still sits on the critical path for essentially the whole corpus, but through a
different door: the shipped view canonicalizes **every component** of every reaction, at
a mean of 4.75 inputs and 1.07 outputs per row. That is ~14.1M canonicalizations against
90,000 reaction-SMILES generations. Finding 1's cost model ("proto reads + RDKit
canonicalization") holds and the RDKit half still dominates — budget tier 1 as an RDKit
job, not a parse job — but the lever is component count, not whether a dataset stored
its reaction SMILES.

### 9. Compacted views are unnecessary — column pushdown already does the work

Earlier drafts published a second artifact: the corpus sorted on a selective column so
DuckDB could prune row groups on min/max statistics. Measuring where the bytes actually
live retires it. Per-column compressed sizes across the 53 derived files:

| column | share of bytes |
| --- | --- |
| `reaction_smiles` | 61.2% |
| `input_smiles` | 14.1% |
| `reaction_id` | 13.5% |
| `output_smiles` | 8.8% |
| **all numeric filter columns combined** | **1.88%** |

SMILES are 84.2% of the corpus; `yield_percent` is 1.06%. So a predicate like
`yield_percent > 70` reads roughly **3.5 MB across the whole corpus**, because parquet
projection pushdown never touches the SMILES column chunks. Sorting exists to make
row-group pruning effective — but there is nothing worth pruning in 3.5 MB. Row-group
statistics are also already written on every column chunk (verified `is_stats_set` on
all 2,466 row groups in the derived output), so within-file pruning works today with no
extra artifact.

The one access pattern sorting would genuinely help is a *selective filter with a wide
projection* — "reaction SMILES where yield > 90%" — where unsorted data means nearly
every row group holds a match and the full 277 MB of SMILES gets read. At this corpus
size that is a few seconds against a CDN, which does not justify a second artifact with
its own staleness, stamping, and verification surface.

**So v1 publishes one artifact: `views/xx/ord_dataset-<id>.parquet`, mirroring `data/`
one-for-one.** Revisit if real query telemetry shows the wide-projection pattern
dominating — at which point the sort key can be chosen from evidence instead of guessed,
which matters because no single key serves both range filters and component-SMILES
lookup.

## Conclusions / next steps

### Settled

**D1 — labels are out of v1.** No `reaction_class`/`reaction_name`. This removes
rxnmapper and torch from the pipeline entirely and decouples v1 from GPU provisioning
(see [2026-07-02](../2026-07-02-full-ord-e2e-run-classification-wall/README.md), where CPU
classification measured ~0.7 rxn/s → ~40 days for the full corpus). Tier 1 alone already
unlocks most agent queries the current API cannot answer. Finding 5's corpus-wide
SMILES→class cache moves to tier 2, post-v1.

**D2 — per-component input/output SMILES ship; `is_negative_result` does not.**
Components are non-negotiable because they are what reproduces `ReactionComponentQuery`,
the most-used predicate in the existing API: it is role-aware (INPUT vs OUTPUT) and
component-level. Splitting a reaction SMILES on `>` does not reproduce it — the agents
field conflates reagents, solvents, and catalysts, and for the 44/52 datasets where the
reaction SMILES is *generated* (finding 8), `allow_incomplete=True` silently drops
components lacking structural identifiers, so the generated string is lossy relative to
the components it came from. The +31% (75.5 MB corpus-wide) is the price of the query
surface actually working.

**`is_negative_result` is cut.** It was included to serve the "give us your failures"
campaign — there is currently no way to *find* the failures we collect. But the proto
has no such field, so the column would have to invent a threshold, and the threshold is
contested: is a negative result a measured zero, or below the assay noise floor, or
under some method-dependent cutoff? Measuring the corpus shows the choice is not
cosmetic:

| definition | share of measured yields |
| --- | --- |
| exactly 0 | 16.1% |
| < 1% | 18.9% |
| < 5% | 25.1% |
| < 10% | 29.9% |

`< 5%` captures **1.56×** as many reactions as `exactly 0` — a 9-point swing, 21,452
rows in the sampled corpus. Publishing one of these as a boolean would impose a
scientific judgment on every consumer, invisibly. That violates the policy-free clause
in finding 1.

Nothing is lost by cutting it. The discoverability problem was never the missing
boolean — it was that yields were unreachable without deserializing every proto, which
tier 1 fixes. A consumer writes `WHERE yield_percent < 5` and picks their own threshold,
and finding 9 shows that predicate reads about **3.5 MB** corpus-wide because
`yield_percent` is 1.06% of the bytes. There is no materialization to save.

The nullable `yield_percent` also dissolves the three-state awkwardness that made this a
sub-question: `yield_percent IS NULL` already distinguishes "no measurement" from
"measured zero," and it matters — **55.0% of rows carry no yield measurement at all**
(45.5% of USPTO, 80.3% of everything else), so a boolean would have been null for more
than half the corpus regardless.

**D5 — one repo: both derived tiers go in the existing `ord-data` HF dataset.** Not a
separate `ord-data-derived`. The reasons are stronger than "it's simpler":

- **A commit SHA pins source and derived together.** Leaving git gave up atomic
  (source, derived) pairing by commit; one HF repo gets it back, because the mirror
  commit contains both. Two repos would leave correlation to footer stamps alone.
- **It fixes the landing experience.** The `default` config in `build_configs` is
  currently the two-column blob schema — the least browsable thing in the repo. With
  derived data in the same repo, the flat facts columns can *become* the default config,
  so the Data Studio preview shows something legible instead of base64 protobuf.
- **One dataset, one citation.** ORD already has a Zenodo DOI and a `CITATION.cff`. A
  second HF dataset is a second citable artifact nobody asked for and a way to fragment
  attribution.
- **Fewer moving parts downstream.** `ord_schema.huggingface.fetch_dataset` keeps one
  `ORD_DATA_HF_REPO` constant, and `download_from_huggingface.py` already defaults to
  `allow_patterns=["data/**"]`, so people who want only source still don't pay for
  derived.

*The cost, honestly:* re-derivation churns the canonical mirror's history rather than an
isolated repo's. That was the case for splitting. It is weaker than it looks — the HF
repo is a mirror, not the source of truth, so its history can be squashed
(`HfApi.super_squash_history`, available in the pinned `huggingface_hub`), which is
precisely the escape hatch git does not have. At 2.43 GB + 334 MB the combined repo is
also well within normal HF sizes.

*Changes if:* derived data grows a lifecycle genuinely independent of the source — many
tier-2 producers, frequent re-derivation, or third-party contributions to
`annotations/` — at which point splitting stops being premature.

**D6 — the prefixes are `views/` and `annotations/`.** "Derived" was the wrong word for
tier 1: it promises added information the tier deliberately does not add. `views/` names
the *contract* rather than the shape — a materialized view cannot disagree with its base
table, and if it does it is stale and wrong, which is finding 1's tier-1 contract stated
in one word. Regenerability is implied for free. Naming a public dataset path is close to
a one-way door, so the shortlist and the rejected candidates are worth recording:

| candidate | verdict |
| --- | --- |
| **`views/`** | **chosen** — encodes the contract in the vocabulary that already has a word for it |
| `tables/` | runner-up, revisited and set aside; accurate and collision-free, but names shape rather than contract |
| `facts/` | good pairing with `annotations/` (measured facts vs. model assertions), but assumes dimensional-modeling vocabulary |
| `flat/` | **rejected** — inaccurate. D2 ships `list<string>` component SMILES, which are repeated fields, not flat |
| `standardized/` | **rejected** — collides with `rdMolStandardize` |
| `normalized/` | **rejected** — collides worse; `Normalizer` is literally an `rdMolStandardize` class |
| `columnar/` | **rejected** — parquet already *is* columnar, so `data/` is too |
| `extract/` | **rejected** — collides with the repo's own language for patent text-mining |
| `index/` | **rejected** — overpromises; no index is built |
| `scalars/` | **rejected** — same list-column inaccuracy as `flat/` |
| `summary/` | **rejected** — implies aggregation; the grain is one row per reaction |

The chemistry collisions are the ones that would actually have caused harm. In
cheminformatics, "standardization" and "normalization" are terms of art for *molecular*
standardization — salt stripping, charge neutralization, tautomer canonicalization. A
chemist seeing `standardized/` in an ORD dataset would reasonably infer the structures
went through that pipeline. **They have not.** We canonicalize SMILES and convert units;
we touch no salt forms, charges, or tautomers.

**`views/` survives the obvious objection**, which is worth writing down because it will
recur: *tier 1 generates reaction SMILES that do not exist in the source and converts
units to a standard basis — so is it really a "view" onto the raw data?* Yes. A SQL view
is a **named query**, not a projection; its defining SELECT may contain arbitrary
computed expressions, function calls, and UDFs. `SELECT temp_c + 273.15 AS temp_k` is a
view. `SELECT first || ' ' || last AS full_name` is a view, and nobody argues `full_name`
disqualifies it for not existing in the base table. Generating a reaction SMILES from
components is likewise a deterministic function of those components — role-based
grouping plus canonicalization — and creates no information.

The defining property of a view is **derivability and determinism**, not simplicity: it
holds no independent truth, because it is defined by its query over base tables. A
*materialized* view stores the result, can therefore go stale, and is fixed by
refreshing. That is finding 1's tier-1 contract exactly, in vocabulary that already
exists.

The vocabulary also draws the tier boundary for free: **tier 2 could not be a view.** A
model's classification is not derivable from base data by a deterministic query, which
is precisely why it is `annotations/`.

*The obligation the name creates* is that the dataset card states **the view
definition** — which proto fields map to which columns, and in what unit basis — so the
derivability claim is checkable rather than asserted. That is the part a user cannot
infer from the artifact.

`materialized_views/` was considered and rejected. The virtual-versus-materialized
distinction is live inside a database, where a view may be computed on read; here the
artifact is a parquet file on a CDN, and its existence *is* the materialization, so the
format already carries what the longer name would say. The nearest precedent agrees:
dbt names its output `models/` and treats `materialized=` as a config, and no SQL engine
names a schema namespace after the storage strategy. The longer name would also
over-specify — shipping DuckDB view definitions as `.sql` alongside the parquet is a
plausible later addition, and `views/` accommodates both renditions where
`materialized_views/` would be wrong for one of them.

*Reconsidered and reaffirmed.* `tables/` was revisited on the grounds that "view" reads
as pure projection to anyone who has not met the SQL definition — a real cost, since the
doubt arose from inside the design. It is a weaker objection than the one that killed
`standardized/`: that name invited an inference that was **false** (structures went
through salt/charge/tautomer handling — they did not), whereas "view" invites one that
is merely **too narrow**, and the corrected reading is more informative than `tables/`
because it encodes the contract rather than the shape. `views/` stands. The other
objection that nearly disqualified it — a collision with "compacted views" elsewhere in
the design — evaporated when finding 9 retired that artifact, so "view" now means
exactly one thing here.

### Still open

Nothing. Every decision above is settled; what follows is implementation.

### Follow-ups that are not decisions

- Add the derived-tier guard to `submission.yml`, and resolve the fork-only gap in
  `check_file_types` noted in finding 7. With sidecars out of git this is an absolute
  reject rather than a provenance check.
- Write the CI-must-not-touch-`annotations/**` invariant into `upload_to_huggingface.py`
  as a comment and a test, per finding 2b.
- Build the derive-then-upload path into `huggingface_mirror.yml` /
  `upload_to_huggingface.py`, which today only knows how to mirror a git diff
  (finding 6), and leave the `CommitOperationDelete` warning in the code.
- Make the derived facts the `default` config in `build_configs` so the Data Studio
  preview stops leading with the two-column blob schema (D5).

### Explicitly deferred

Widening the ORM query surface (new `ReactionQuery` subclasses over the already-indexed
condition tables) is independent of this work and can proceed separately. Likewise the
MCP server: it should expose structured parameters rather than `nl_query`, since routing
an agent's intent through a second translation loses information. Both need a
token-efficient result rendition — `QueryResult` returns base64 protobuf today, and
`MAX_RESULTS = 1000` in `ord_interface/api/search.py` truncates silently with no count
endpoint to detect it.

## References

- Serialization and cache-key primitives: `ord-schema` `ord_schema/parquet.py`
  (`iter_reactions`, `streaming_md5`, `save_dataset` footer KV), `ord_schema/units.py`,
  `ord_schema/message_helpers.py` (`get_reaction_smiles`).
- Label semantics: `ord-schema` `ord_schema/orm/derived_mappers.py` (`ReactionClasses`),
  `ord_schema/orm/reaction_class.py`.
- Query ceiling: `ord-interface` `ord_interface/api/queries.py` (seven `ReactionQuery`
  subclasses), `ord_interface/api/nl_query.py`, `ord_interface/api/search.py`
  (`MAX_RESULTS`).
- `ord-data` CI and publishing: `.github/workflows/validation.yml` (nine-way shard
  matrix, USPTO special case), `.github/workflows/submission.yml`
  (`check_file_types`), `scripts/upload_to_huggingface.py` (`MIRROR_PATHSPECS`),
  `.lfsconfig`.
- Scoping-run script, per-dataset results, and reproduction guide:
  [`ASSETS.md`](ASSETS.md).
- Shipped implementation, and the source of the re-measured figures: `ord-schema`
  `ord_schema/views.py` and `ord_schema/scripts/derive_views.py`, in
  [ord-schema#914](https://github.com/open-reaction-database/ord-schema/pull/914).
- LFS cost model behind finding 6: Git LFS stores whole objects with no delta encoding
  and `git lfs prune` only reclaims locally
  (<https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md>). Measured on `ord-data`
  2026-07-25: 4.54 MiB of git objects over 112 commits against 2.43 GB of LFS objects at
  HEAD and 5.88 GB across 1,235 objects over all refs.
- Companion entry: [2026-07-25 native sharding within a dataset ID](../2026-07-25-native-sharding-in-data/README.md)
  (shared part-directory mechanism for `data/`).
- Prior entries: [2026-07-02 full-ORD end-to-end run](../2026-07-02-full-ord-e2e-run-classification-wall/README.md)
  (classification CPU wall), [2026-07-02 reaction classification](../2026-07-02-reaction-classification/README.md),
  [2026-06-26 natural-language query interface](../2026-06-26-natural-language-query-interface/README.md).
- Hugging Face mirror: <https://huggingface.co/datasets/open-reaction-database/ord-data>.
