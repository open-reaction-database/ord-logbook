# Can the source Parquet replace Postgres behind ord-interface?

- **Date:** 2026-10-03
- **Author:** Steven Kearnes
- **Acknowledgments:** Prepared with [Claude Code](https://claude.com/claude-code) (Claude Opus 5.5)
- **Status:** draft (measurements final; deprecating the ORM is proposed, not decided)
- **Tags:** ord-schema, ord-interface, ord-infrastructure, orm, postgres, parquet, duckdb,
  search, deployment
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

ord-interface reads one Postgres database, the one `ord_schema.orm` defines and
`ord_schema.orm.scripts.add_datasets` loads, for four things: search, reaction details,
dataset metadata, and per-dataset statistics. Search is moving to `ord_schema.search`,
whose last open question for the swap was where result details come from
([2026-10-02](../2026-10-02-what-the-search-api-still-needs/README.md#4-where-result-details-come-from)).

If the source Parquet files in ord-data can serve reaction details, nothing left in
ord-interface needs Postgres and the ORM can be deprecated. So: is fetching a reaction by
ID from the source Parquet fast enough, and what else would have to move?

## Summary

**Yes. DuckDB reading the source files directly returns any batch ord-interface asks for
in under 0.2 s, with no index and no state, and every other Postgres read has a route on
the artifacts.**

| route | 1 ID | 100 IDs | 1,000 random IDs | a search's 1,000 hits |
| --- | ---: | ---: | ---: | ---: |
| DuckDB over the sources, ID filter pushed down | 22 ms | 0.19 s | 0.19 s | 0.18–0.20 s |
| source and row known, row groups read directly | 2 ms | 27 ms | 0.24 s | not run |
| in-memory ID index (1.6 s and 573 MiB to build) | 2 ms | 26 ms | 0.17 s | 1–17 ms |

Warm medians of three. The second and third routes read the same row groups, so the
second's search-page times should match the third's. ord-interface fetches at most 1,000
reactions at a time
(`MAX_RESULTS`), and what it returns is each reaction's serialized proto, which is
exactly what the source files store, so no reaction is parsed to serve it.

- **Cost follows row groups, not IDs.** Reading one reaction decompresses its row group,
  a median 572 KiB of zstd. A search's hits cluster: the first 1,000 amide couplings sit
  in 76 row groups, 1,000 high-yield reactions in 9, a small dataset's 750 in 1.
- **A projection's row is its source's row**, in all 53 datasets, so a search could
  return each hit's position and make a fetch a direct row-group read. Finding the
  position afterwards costs 0.7–0.9 s, so it would have to come out of the search.
- **The corpus and the sources are one snapshot.** Every projection's stamped source MD5
  matches a local source file. Postgres is a second copy whose agreement nothing checks;
  checking this one costs 11.7 s, once.

**Recommendation: serve details with DuckDB over the source files, and deprecate the ORM
once ord-interface has moved.** Returning positions from the search is the upgrade if the
single-reaction view ever needs better than 22 ms.

## Method

- **Data.** The 53 source files of ord-data at `83f971f` and the local projection tree
  derived from them (53 datasets, 2,428,291 reactions; derived as in
  [2026-10-02](../2026-10-02-what-the-artifact-stamps-cannot-see/README.md#method)), on
  the 24 GiB laptop with DuckDB 1.5.5, PyArrow 24.0.0, and Python 3.11. The files fit in
  memory and every timing is with them in the OS page cache.
- **Layout.** [`layout.py`](assets/layout.py) reads row-group metadata
  ([`layout.txt`](assets/layout.txt)).
- **Workload.** ord-interface `fetch_reactions` at `32d1565`: up to 1,000 IDs in, each
  reaction's dataset ID and serialized proto out. [`fetch.py`](assets/fetch.py) fetches
  random sets of 1, 10, 100, and 1,000 IDs (seed 7) and the hits of three searches: the
  first 1,000 matches of `C(=O)O.N>>C(=O)N`, the first 1,000 reactions with a yield above
  90%, and all 750 reactions of `ord_dataset-00005539…`. Each route is timed on its first
  call and as the median of three more, and checked to return exactly the IDs asked for,
  in order, each blob parsing to a Reaction with that ID
  ([`fetch.txt`](assets/fetch.txt), [`fetch.json`](assets/fetch.json)).
- **Routes.** *Direct*: `read_parquet` over all 53 sources with
  `reaction_id IN (SELECT unnest($ids))`. *Indexed*: a Python dict from reaction ID to
  file, row group, and offset, then PyArrow reads of those row groups' `reaction` column,
  on one thread and on eight. *Positional*: the same reads, starting from each ID's
  source file and row number.
- **Alignment and verification.** [`fetch2.py`](assets/fetch2.py) hashes every source
  with `DatasetView.md5`, pairs each projection with the source its stamp names,
  compares the two `reaction_id` columns, and times the positional route, direct reads
  restricted to the files the IDs come from, and finding positions after the fact
  ([`fetch2.txt`](assets/fetch2.txt)). The positional route's output is checked
  byte-for-byte against the direct route's.
- **Statistics.** [`stats.py`](assets/stats.py) runs ord-interface's most-used-SMILES
  queries as search API aggregates for the USPTO dataset and the small one
  ([`stats.txt`](assets/stats.txt)).
- **Consumers.** `git grep` at `origin/main` of ord-interface `32d1565`, ord-app
  `87ca9d5`, ord-infrastructure `4a2f902`, and ord-data `83f971f`, for ORM imports, SQL
  against the ORM's schemas, and Postgres settings.
- **Not measured.** A cold page cache, sources on S3 rather than local disk, concurrent
  requests, and production Postgres for comparison.

## Findings

### 1. The layout sets the cost

| | |
| --- | --- |
| files | 53, one per dataset; the USPTO file holds 1,771,032 reactions |
| row groups | 2,466, of at most 1,000 reactions |
| `reaction` column | 1,145 MiB zstd, 6,526 MiB uncompressed |
| one row group of `reaction` | median 572 KiB compressed, about 2.6 MiB uncompressed |

A reaction is one row, but the smallest unit a reader decompresses is its row group's
column chunk. A fetch costs what the row groups it touches cost, and how many it touches
depends on how the IDs are spread rather than how many there are. Random IDs are the worst
case: 1,000 of them touch 836 row groups.

### 2. Three routes

| IDs | direct | indexed, 1 thread | indexed, 8 threads | positional, 8 threads | row groups | MiB returned |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 random | 0.022 s | 0.002 s | 0.002 s | 0.002 s | 1 | 0.00 |
| 10 random | 0.192 s | 0.015 s | 0.005 s | | 10 | 0.02 |
| 100 random | 0.185 s | 0.120 s | 0.026 s | 0.027 s | 99 | 0.29 |
| 1,000 random | 0.187 s | 1.057 s | 0.165 s | 0.244 s | 836 | 2.65 |
| amide hits, first 1,000 | 0.183 s | 0.092 s | 0.017 s | | 76 | 2.69 |
| yield above 90%, first 1,000 | 0.191 s | 0.014 s | 0.004 s | | 9 | 2.96 |
| one dataset, 750 | 0.196 s | 0.001 s | 0.002 s | | 1 | 1.41 |

- **Direct** scans every source's `reaction_id` column, 2.4 million IDs, and reads the
  `reaction` column only where an ID matched. That scan is a floor of about 0.19 s for
  any batch past one ID, and it does not grow with the batch. It needs nothing built or
  held; a batch's first call costs up to 0.28 s. Restricting the scan
  to the files the IDs come from brings one ID to 15 ms and leaves 100 or 1,000 random
  IDs, which touch most of the corpus, where they were.
- **Indexed and positional** read only the row groups the IDs fall in, so they track the
  row-group column of the table: single-digit milliseconds for a clustered search page,
  0.17–0.24 s for 1,000 scattered IDs on eight threads. Both read the same row groups;
  they differ in where the location comes from. The dict costs 1.6 s at open and 573 MiB
  resident; the positional route needs no structure of its own but has to be told each
  hit's source and row (finding 3).
- A 1,000-reaction download is about 3 MiB of serialized protos.

### 3. A projection's row is its source's row

All 53 projections hold exactly their source's `reaction_id` column, row for row. The
search's relation already reads the projection files, so it could carry each row's file
row number at no extra scan, and a hit's source position would come back with its ID.
Finding the positions afterwards, by scanning the projections for the IDs, costs
0.7–0.9 s, more than the direct route, so the position is only worth having if the search
returns it.

`projection.write_projection` writes rows in source order, and two of its tests assert
it in passing (`test_write_projection_round_trips`,
`test_write_projection_covers_every_row_group`). Nothing states it as a contract, though,
and nothing checks it on a built corpus. A route that depends on it should make it both.

### 4. The corpus and the sources are one snapshot

Hashing every source with `DatasetView.md5` takes 11.7 s, and each of the 53 projections'
`ord.source_md5` stamps names one of the local files. So the reactions a search finds and
the reactions a fetch returns come from the same files, and that is checkable at open.
With Postgres the two are separate loads of ord-data that have to agree, and
`Corpus.fingerprint` can name the artifact side only.

### 5. Every other Postgres read has a route

| ord-interface reads | from Postgres today | on the artifacts |
| --- | --- | --- |
| `/query`, `/ask` | the `ord` schema, `rdkit.mols`, `rdkit.reactions` | the search API, at parity since ord-schema#1091–#1093 |
| `/reaction`, `/reactions`, `/download_search_results` | `public.reactions.proto` | DuckDB over the sources (findings 1–2) |
| `/datasets`, `/dataset`: name, description, reaction count | `ord.dataset`, `public.datasets` | each source's footer: `ord.name`, `ord.description`, row count |
| `/datasets`, `/dataset`: `submitted_at` | `public.datasets`, set at load from one reaction's last record event | the projection's provenance dates, which wait on the [date decisions](../2026-09-03-date-time-formats/README.md) |
| `/input_stats`, `/product_stats` | a `GROUP BY` over derived SMILES | an `aggregate.over` the components or products, filtered by `dataset_id` |

The two statistics run as search API aggregates in 0.04–0.93 s on their first ask and
0.04–0.17 s repeated, the slowest being the USPTO dataset's inputs. Their SMILES are the
projection's, which may be canonicalized differently from the ORM's derived SMILES; the
two have not been compared.

### 6. ord-interface is the ORM's only reader

- **ord-interface** imports `ord_schema.orm.database.get_connection_string` and runs SQL
  against the ORM's `ord`, `derived`, `rdkit`, and `public` schemas.
- **ord-app** imports nothing from the ORM; its compose file runs a Postgres of its own.
- **ord-infrastructure** provisions the Aurora cluster and passes its endpoint and
  database name to ord-interface's tasks.
- **ord-schema** holds `ord_schema/orm`, the `add_datasets` loader, the
  `orm-database-load` skill, and the 61 tests that need a Postgres server.

## Conclusions / next steps

1. **Move ord-interface in one step**, as planned: search through `ord_schema.search`,
   details with DuckDB over the source files, dataset metadata from the source footers,
   and the statistics as aggregates. The sources add 1.2 GiB to what a deployment holds
   beside the artifacts.
2. **Settle the date decisions**, which `submitted_at` needs.
3. **Deprecate `ord_schema.orm`** in the release after ord-interface stops importing it,
   so the warning reaches anyone else still loading a database.
4. **Stop loading Aurora** and retire the `orm-database-load` skill.
5. **Remove the ORM** and its Postgres-backed tests in a later release.

Revisit the route, not the decision, if the sources move to S3: the direct route reads
every ID column on every fetch, which costs more over a network, and positions returned
by the search would then pay for their alignment check.

## References

- [`assets/`](assets/): `layout.py` and `layout.txt`, `fetch.py`, `fetch.txt`, and
  `fetch.json`, `fetch2.py` and `fetch2.txt`, `stats.py` and `stats.txt`.
- [What the search API still needs before ord-interface can use it](../2026-10-02-what-the-search-api-still-needs/README.md)
  — finding 4, the question this answers.
- [Unlocking agents: tabular sidecars, the ORM, or both](../2026-07-30-agent-access-sidecars-or-orm/README.md)
  — why queries moved from the ORM to the projection.
- ord-schema `ord_schema/parquet.py` — the source format: one row per reaction, its
  serialized proto beside its ID.
- ord-interface `ord_interface/api/search.py` and `ord_interface/api/queries.py` — the
  endpoints and SQL this would replace.
