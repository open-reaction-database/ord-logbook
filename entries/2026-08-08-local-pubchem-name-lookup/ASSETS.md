# Measurement scripts

Scripts behind [2026-08-08 a local PubChem name lookup](../2026-08-08-local-pubchem-name-lookup/README.md).

Run them from an environment with `duckdb` and `rdkit` installed. The build needs the
two PubChem bulk files and roughly 25 GB of scratch (DuckDB spills ~18 GB while
grouping 118M synonyms):

```bash
mkdir -p /tmp/pubchem && cd /tmp/pubchem
curl -O https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-SMILES.gz
curl -O https://ftp.ncbi.nlm.nih.gov/pubchem/Compound/Extras/CID-Synonym-filtered.gz
```

Then, in order:

```bash
python prep_testset.py                                      # -> testset.tsv
python build_index.py /tmp/pubchem /tmp/index               # -> parquet + sqlite
python probe_api.py testset.tsv 400 api_probe_misses.tsv --prior none
python eval_lookup.py /tmp/index testset.tsv api_probe_misses.tsv eval
python analyze_index.py /tmp/index testset.tsv /tmp/index   # -> slim index
python probe_api.py testset.tsv.gz 400 cir_probe_index_misses.tsv \
  --service cir --prior all --names index_misses.txt.gz
python normalize_gap.py /tmp/index testset.tsv
python coverage_union.py eval_local_hits.tsv
python review_top_hits.py eval_local_hits.tsv 60 top_hits_reviewed.tsv
```

| script | produces |
| --- | --- |
| `prep_testset.py` | the evaluation set: the 46,831 candidate names from 2026-07-11 with their ORD row counts and prior resolver outcome |
| `probe_api.py` | live PUG REST results for a sample of names — status, SMILES, line count, latency, and PubChem's own throttle header |
| `build_index.py` | the full index, as ZSTD Parquet and as SQLite, with per-step build timings (findings 1 and 5) |
| `eval_lookup.py` | coverage over the ORD name-only set, structural agreement with the live API, and lookup latency (findings 2, 3, 5) |
| `analyze_index.py` | what the index is made of, and the slim index that drops machine identifiers (finding 6) |
| `normalize_gap.py` | hits recovered by folding lookalike punctuation before lookup (finding 4) |
| `coverage_union.py` | ORD row coverage of the index alone and unioned with the 2026-07-11 results (finding 2) |
| `review_top_hits.py` | hand-graded verdicts on the 60 highest-impact answers (finding 7) |
| `bench_opsin.py` | local OPSIN through `py2opsin` — batch and per-name timings, and agreement with the EBI web service (finding 9) |
| `chembl_overlap.py` | what ChEMBL's synonyms add over the PubChem index (finding 10) |

`prep_testset.py` and `coverage_union.py` read the
[2026-07-11 assets](../2026-07-11-name-only-compounds/README.md) by relative path, so run them
from this directory.

Data files committed here:

| file | contents |
| --- | --- |
| `testset.tsv.gz` | `name⇥rows⇥prior` for the 46,831 candidate names; `prep_testset.py` regenerates the uncompressed form |
| `top_names.txt` | the 300 candidate names with the most ORD rows |
| `api_probe_misses.tsv` | 400 names the 2026-07-11 pass left unresolved, probed live |
| `api_probe_top.tsv` | the 300 highest-frequency names, probed live |
| `cir_probe_index_misses.tsv` | 400 names the local index missed, probed against NCI/CADD CIR |
| `index_misses.txt.gz` | the 43,395 candidate names the local index does not resolve |
| `eval_local_hits.tsv.gz` | every candidate name with the SMILES the local index returned, empty on a miss |
| `opsin_local.tsv.gz` | every candidate name with the SMILES local OPSIN returned, py2opsin defaults |
| `top_hits_reviewed.tsv` | the 60 highest-impact hits with a manual `ok`/`label` verdict |

`bench_opsin.py` needs a JRE and `py2opsin`:

```bash
mamba install -c conda-forge openjdk && pip install py2opsin
export PATH="$CONDA_PREFIX/lib/jvm/bin:$PATH"
python bench_opsin.py testset.tsv.gz \
  ../2026-07-11-name-only-compounds/resolver_results.tsv.gz opsin_local.tsv
```

The probe scripts pace themselves at 3 requests/second, below PubChem's documented
ceiling of 5/second and 400/minute. **CIR does not tolerate that rate** — it dropped the
TLS connection on 368 of 400 requests and then blocked the host, so
`cir_probe_index_misses.tsv` is mostly `URLError` by design of the finding, not by
accident. Re-running it will likely get you blocked too.

Timings are single-process on an Apple M5 Pro laptop with 25 GB of RAM.
