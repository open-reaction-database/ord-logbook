# Native sharding within a dataset ID

- **Date:** 2026-07-25
- **Author:** Steven Kearnes
- **Status:** draft (proposal; not yet implemented)
- **Tags:** ord-data, ord-schema, parquet, sharding, git-lfs, huggingface, design

## Question

`ord-data` has sharded large datasets **across many dataset IDs** — 489 monthly
`uspto-grants-YYYY_MM` buckets, ten `Training data … (N/10)` pieces. PR #241 undid that
by merging each group into one parquet file. Should `data/` instead support sharding
**within** a single dataset ID, as a first-class layout?

Scope: **parquet only.** `.pb.gz` is deprecated (`155261c`) and gets no sharding
support — it stays exactly as it is.

## Summary

**Yes — shard within the ID, and never across it.** The distinction that matters is
*why* a dataset is being split:

- **Size shards** — pieces of one logical dataset, split only because the whole is
  large. These must share a dataset ID. Splitting them across IDs is what we did, and
  it was wrong.
- **Semantic splits** — pieces that are separately meaningful and separately citable
  (`uspto-mit` train/validation/test). These are legitimately distinct datasets and
  should keep distinct IDs.

Cross-ID sharding conflated the two and made the *citable unit of provenance* a
function of file size. Un-sharding in #241 fixed the semantics but produced a **1.04 GiB
single-object dataset that is 89% of all parquet bytes in the repo** — and Git LFS
stores whole objects with no deltas, so a one-reaction fix to USPTO writes another
1.04 GiB blob into history, permanently.

Native intra-dataset sharding gets both: one ID, and a rewrite unit small enough that
edits are cheap. The concept already exists inside the code — `validate_dataset.py`
fans out one task per row group, and the ORM ingest shards the same way — so this makes
an existing internal decomposition durable on disk, where it also buys LFS churn
locality.

**The recommendation is to design it, not to build it yet.** Today only USPTO crosses
any plausible threshold, so N=1. The original tiebreaker was that the derived-sidecar
design needed part directories for the same file — but that entry's measurements
subsequently retired them (sidecars are HF-only, and a full USPTO rederivation takes ~32
seconds, so there is nothing to make incremental). **That second consumer is gone.**

What survives is the *semantic* result below — the size-shard versus semantic-split rule
— which is worth writing down regardless of whether any code gets built. See D1.

## Method

Read the layout, conversion script, CI, and publishing path in `ord-data` at `main`
(`e017725`), and the serialization and path helpers in `ord-schema` (`67a63c7`).
Corpus numbers come from reading the parquet footers directly (`pyarrow.parquet`,
footer KV only — no reaction decode) and from `git`/`stat` over the working tree on
2026-07-25.

Note the `.pb.gz` objects are LFS pointers in this checkout, so all row counts below are
from the parquet side.

## Findings

### 1. The corpus records both patterns, and the numbers are lopsided

| quantity | value |
| --- | --- |
| distinct dataset IDs under `data/` | 552 |
| IDs with a `.parquet` | 53 |
| IDs with a `.pb.gz` | 550 |
| IDs with both | 51 |
| `.pb.gz`-only (merged away by #241) | 499 |
| `.parquet`-only (the two merge outputs) | 2 |

Those 499 decompose exactly as `scripts/convert_to_parquet.py` documents in
`MERGE_SPECS`: **489 `uspto-grants-YYYY_MM` monthly buckets** plus **10
`Training data from …/C8SC04228D (N/10)` shards**. Both groups were one logical dataset
wearing hundreds of dataset IDs.

Reaction counts in the 53 parquet files total 2,428,291 — matching the full-ORD ingest
in [2026-07-02](2026-07-02-full-ord-e2e-run-classification-wall.md) — and the
distribution is extreme:

| dataset | reactions | row groups | bytes |
| --- | --- | --- | --- |
| `uspto-grants` (`1158e351…`) | 1,771,032 | 1,772 | 1,112,719,074 |
| next largest (`e7830cd6…`, C8SC04228D train) | 409,035 | 410 | ~99.8 MB |
| all 53 parquet files | 2,428,291 | — | ~1.17 GB |

USPTO is **73% of the reactions and ~89% of the parquet bytes.**

### 2. Cross-ID sharding was wrong for four concrete reasons

- **It made the citable unit a function of file size.** `dataset_id` is what a paper
  cites and what `Reaction.provenance` hangs off. Minting 489 of them for one patent
  extraction means no one can cite "USPTO grants" — they cite an arbitrary month.
- **It broke identity on repair.** Un-sharding could not reuse any source ID, so #241
  minted a *new* derived ID (`sha256` of the sorted source IDs, first 32 hex chars).
  Every previously published `uspto-grants-YYYY_MM` ID is now dangling. Cross-ID
  sharding is therefore a one-way door: you cannot consolidate without an ID break.
- **It leaked into every consumer.** The residue is still visible: the HF card's
  `uspto-mit` config stitches three dataset IDs together as `train`/`validation`/`test`
  splits (`USPTO_MIT_SPLITS` in `scripts/upload_to_huggingface.py`). That one is
  *legitimate* — see the semantic-split distinction — but it shows the shape consumers
  are forced into when the file layout can't express "several files, one dataset."
- **It gave no locality benefit anyway.** Monthly buckets are not the granularity edits
  arrive in, and 489 dataset-level validation tasks are a worse fan-out than the
  row-group fan-out `validate_dataset.py` already does.

### 3. Un-sharding traded that for an LFS churn problem

Git LFS stores whole objects — there is no delta encoding. The USPTO parquet has been
written once (`32dcc87`); the next content edit to it adds a second 1.04 GiB object,
and every clone that walks history pays for both. `updates.update_parquet_dataset` is a
full two-pass rewrite of the input file, so *any* update touches all 1.77M rows
regardless of how few changed.

`.lfsconfig` routes clone/fetch reads to the Hugging Face mirror precisely because
GitHub LFS bandwidth is scarce. Writes still land on GitHub, so object churn is a real
and asymmetric cost.

CI already pays for this shape. `validation.yml` has a dedicated `validate_parquet`
matrix leg for the USPTO file alone, with the other leg carrying a negative-lookahead
regex to exclude it — a special case that exists solely because one dataset is a
different order of magnitude.

### 4. Intra-dataset sharding already exists — just not on disk

- `validate_dataset.py` submits **one task per row group** for parquet inputs and
  merges per-file cross-reference state afterward. Its own module docstring says this
  is so `--n_jobs` "actually saturates on a single large dataset."
- The ORM ingest and derived passes shard by row group (ord-schema #879/#883/#887/#888).
- `DatasetWriter` writes a new row group every `row_group_size` rows (default 1000) —
  hence USPTO's 1,772 groups.

So "a dataset is processed in parts" is already true everywhere it matters. What is
missing is that the parts aren't durable, so nothing downstream — LFS, CI's LFS pull,
the HF mirror diff — can address one.

### 5. Proposed layout

A dataset is **either** a file **or** a directory of parts:

```text
data/00/ord_dataset-00005539….parquet              # small: unchanged
data/11/ord_dataset-1158e351…/part-00000.parquet   # large: parts
data/11/ord_dataset-1158e351…/part-00001.parquet
```

Invariants that make this safe:

1. **Every part carries identical footer scalars** (`ord.dataset_id`, `ord.name`,
   `ord.description`, `ord.schema_version`). Validation enforces equality across parts;
   a mismatch is an error, not a merge.
2. **Parts are immutable once written.** An edit rewrites only the part containing the
   changed reactions; part numbering is append-only. Rebalancing on every edit would
   destroy the churn locality that is the entire point.
3. **The directory listing is the manifest.** No index file to reconcile — the same
   reasoning as the sidecar design's per-dataset choice.
4. **Reaction IDs stay unique across the whole part set,** which means the cross-ref
   merge in `validate_dataset.py` moves up one level: from per-file to per-dataset.
5. **Publication is per-part-atomic, dataset-eventual.** `DatasetWriter`'s temp+rename
   already makes each part atomic; a part set is valid iff every part validates. A
   half-written directory fails validation rather than corrupting a good file.

### 6. What breaks: every site that computes a path from an ID

These assume one dataset = one file at a derivable path:

| site | assumption | change |
| --- | --- | --- |
| `message_helpers.id_filename` | returns `data/<2-hex>/<basename>` | needs a part-directory form; it is also the shared safety check (`..`/absolute-path rejection), so the guard must extend, not fork |
| `huggingface.fetch_dataset` | `hf_hub_download` of one `filename` | must resolve a part set (`snapshot_download` with a prefix) |
| `upload_to_huggingface.build_configs` | `glob("data/*/*.parquet")`, `data_files: [one path]` | glob one level deeper; `data_files` already accepts lists/globs, so Data Studio survives |
| `validation.yml` | `--input="data/*/*.parquet"`, LFS `--include='data/*/*.parquet'` | both need the nested form; the nine-way `data/[0-4][0-4]` shard globs still work |
| `submission.yml` | changed-file list → dataset, one path per dataset | must group changed parts by dataset before calling `process_dataset` |
| `updates.update_parquet_dataset` | whole-file two-pass rewrite | needs a part-scoped path to realize any benefit |
| `parquet.DatasetView` / `load_dataset` / `iter_reactions` | one path | need a dataset-level handle over an ordered part set |

Two things already work unchanged and are worth noting because they constrain nothing:
`.gitattributes` uses `data/**/*.parquet`, which matches nested directories; and
`download_from_huggingface.py` defaults to `data/**`.

### 7. `.pb.gz` gets none of this

Legacy `.pb.gz` is deprecated and frozen: no part directories, no new writers, no
changes to `validate_pb`. The 489 monthly USPTO buckets and the 10 C8SC04228D shards
stay exactly where they are as historical `.pb.gz` artifacts. Sharding is a property of
the parquet serialization only, which also keeps the blast radius of this work inside
`parquet.py` and the parquet CI leg.

## Conclusions / next steps

### D1 — Build native sharding at all? (**Recommend: not now — adopt the rule, defer the mechanism**)

This recommendation has flipped. It previously rode on
[the derived-sidecar design](2026-07-25-derived-parquet-sidecars.md) needing part
directories for the same file, on the same threshold, with the same semantics — two
consumers justifying a mechanism. That entry's measurements removed its half: sidecars
are published to Hugging Face rather than committed, so a rewrite costs nothing
permanent, and a full USPTO rederivation takes ~32 seconds, so there is nothing to make
incremental.

That leaves `data/` alone, at N=1, against a fully general layout change touching seven
path-computing sites (finding 6). Not worth it yet. The LFS churn problem in finding 3 is
real but latent — USPTO has been written exactly once, at `32dcc87`.

*Adopt now, at zero cost:* the size-shard versus semantic-split rule (D4), written into
`CONTRIBUTING.md`. That is what prevents the error recurring, and it needs no code.

*Build if:* USPTO starts taking routine content edits — each one is another 1.04 GiB
LFS object, permanently — or a second dataset crosses the same order of magnitude. The
first repeated edit to `1158e351…` is the trigger to watch.

### D2 — Part boundaries: immutable or rebalanced? (**Recommend: immutable, append-only**)

Churn locality is the entire justification, and rebalancing gives it back. Accept that
parts drift in size as edits accumulate, and treat compaction as an explicit, rare,
deliberately-scheduled operation — never an implicit side effect of an edit.

*Needs deciding alongside:* whether a compaction is allowed to renumber parts (it
rewrites every object either way, so the answer is probably yes, but it should be a
stated policy rather than an accident).

### D3 — Threshold and part size (**Recommend: ~250k reactions/part; threshold at one dataset**)

At 250k rows USPTO becomes ~8 parts of ~150 MB — large enough that part count stays
trivial, small enough that an edit rewrites 8% of the dataset instead of 100%. Set the
file/directory threshold wherever it isolates USPTO today and revisit when a second
dataset crosses it.

*Open:* whether part boundaries should align to row-group multiples (they should — it
makes `validate_dataset.py`'s existing fan-out compose without a second chunking rule).

### D4 — Do the merged IDs get re-sharded, and what about `uspto-mit`? (**Recommend: re-shard USPTO; leave `uspto-mit` alone**)

`uspto-grants` is a size shard and should become a part directory under its existing
`1158e351…` ID — no new ID, since the ID is what #241 already broke once and must not
break again.

`uspto-mit`'s train/validation/test are **semantic splits**: separately meaningful,
separately citable, separately used. They keep their three IDs, and the HF config keeps
stitching them into splits. Collapsing them would repeat the original error in the
opposite direction.

*This distinction is the durable output of this entry* — the rule going forward is
"split by size → one ID, many parts; split by meaning → many IDs." Worth writing into
`CONTRIBUTING.md` so contributors do not reinvent monthly buckets.

### D5 — Where does the part-set abstraction live? (**Recommend: `ord_schema/parquet.py`**)

`DatasetView` is the natural seam — it already presents a streaming, footer-backed
facade that quacks like `dataset_pb2.Dataset`. Extending it to accept a directory keeps
every caller (`process_dataset`, `validate_dataset`, the ORM ingest) unchanged at the
call site.

*Watch for:* `DatasetView.path` is a public property returning a single path and has
callers (`_get_reaction_ids` passes it to `iter_reaction_ids`). That is the one API
that cannot survive unchanged.

## References

- Conversion and the documented merge groups: `ord-data`
  `scripts/convert_to_parquet.py` (`MERGE_SPECS`, `_derive_id`), PR
  [#241](https://github.com/open-reaction-database/ord-data/pull/241) "Convert datasets
  to parquet (un-shard USPTO)" (`32dcc87`).
- Serialization: `ord-schema` `ord_schema/parquet.py` (`DatasetWriter`, `DatasetView`,
  `load_footer`, `iter_reactions`), `ord_schema/updates.py`
  (`update_parquet_dataset`).
- Path and fetch helpers: `ord_schema/message_helpers.py` (`id_filename`),
  `ord_schema/huggingface.py` (`fetch_dataset`).
- Row-group fan-out: `ord_schema/scripts/validate_dataset.py`; ord-schema PRs
  [#879](https://github.com/open-reaction-database/ord-schema/pull/879),
  [#883](https://github.com/open-reaction-database/ord-schema/pull/883),
  [#887](https://github.com/open-reaction-database/ord-schema/pull/887),
  [#888](https://github.com/open-reaction-database/ord-schema/pull/888).
- `ord-data` CI and publishing: `.github/workflows/validation.yml` (USPTO matrix leg),
  `.github/workflows/submission.yml`, `scripts/upload_to_huggingface.py`
  (`build_configs`, `USPTO_MIT_SPLITS`), `scripts/download_from_huggingface.py`,
  `.gitattributes`, `.lfsconfig`.
- Companion entry: [2026-07-25 derived parquet sidecars](2026-07-25-derived-parquet-sidecars.md).
  Its finding 3 originally reached the same part-directory conclusion for `derived/` and
  later retired it on measured evidence, which is what flips D1 here.
- Git LFS stores whole objects, not deltas: <https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md>.
