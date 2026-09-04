# Date and time formats across the corpus

- **Date:** 2026-09-03
- **Author:** Steven Kearnes
- **Status:** findings final; the proposal is not yet accepted, and the day/month order of `5c9a1032` and `5e8318f0` is with their submitters
- **Tags:** ord-data, ord-schema, provenance, datetime, data quality, normalization
- **License:** [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

## Question

`DateTime` is a bare string in the schema, and validation only asks that
`dateutil` can parse it. Nothing normalizes the value on the way in, so whatever
shape the submitting tool produced is what the corpus stores forever.

Before writing a normalizer: what date and time formats are actually in there,
at which schema positions, and can a consumer at least assume one dataset is
internally consistent?

## Summary

**No, a dataset is not internally consistent, and the variety is not the real
problem.** 7,631,369 populated `DateTime` values across 53 datasets and
2,428,291 reactions carry **15 distinct format signatures in 9 families**.
15 of the 108 populated (dataset, position) cells hold more than one family, and
**52 of 53 datasets** write `record_created` in a different format than
`record_modified`. Exactly one dataset — `5415f83d` — is uniform.

**The hazard is `NN/NN/NNNN`.** 41 datasets write a slash-separated date whose
first two fields the string itself does not distinguish. In 28 of them some
value settles it — 25 month-first, **3 day-first**. Bounds, a co-submitted
sibling, the `en-US` 12-hour format, and the supplemental data on two submission
pull requests settle 11 of the remaining 13, for **39 settled: 35 month-first,
4 day-first**. **Two stay open** — `5c9a1032` and `5e8318f0` — and `dateutil`
reads both month-first, which for `5e8318f0` is probably wrong.

**Nothing carries a time zone.** Not one of the 7,631,369 values has a UTC
offset or a zone name — including the 48,498 that ord-app's service writes with
a `Z`, which the UI strips on the contributor's first save.

Four of the schema's seven `DateTime` positions are never populated at all.

The [proposal](#proposal) below normalizes the stored values to ISO 8601 with a
`Z` only where the corpus knows the zone — 32% of it — fixes the producers
first so the rewrite is not immediately undone, and argues for shipping a reader
before paying 1.2 GB of LFS churn.

## Method

A full scan of a local `ord-data` checkout at
[`83f971f`](https://github.com/Open-Reaction-Database/ord-data/commit/83f971f),
53 Parquet datasets, every reaction.

`Reaction` reaches a `DateTime` at seven positions, four of them behind repeated
and map fields deep in `inputs`, `workups`, and `outcomes`. Parsing 2.4M full
reactions to read them is not worth it, so
[`mini_reaction.py`](assets/mini_reaction.py) builds a cut-down message holding
exactly those paths with the schema's own field numbers; everything else becomes
an unknown field the parser skips.

[`scan_date_times.py`](assets/scan_date_times.py) reduces each value to a
signature — digit runs to runs of `N`, month and weekday names to `MON` and
`DAY`, `AM`/`PM` to `AP`, separators kept verbatim — so counting signatures per
dataset and position says both which formats exist and whether a dataset holds
more than one. Output: [`date_time_formats.csv`](assets/date_time_formats.csv).

[`resolve_orientation.py`](assets/resolve_orientation.py) settles day-first
versus month-first from six kinds of evidence, strongest first: a
**confirmation** from outside the corpus, such as the supplemental data on a
submission pull request; a **witness** value whose first field exceeds 12
(day-first) or whose second does (month-first); an **upper bound**, since a
reaction's `record_created` precedes each of its own `record_modified` events
and no value can postdate the last commit to touch the dataset; a **sibling**,
since datasets added by one commit are one submission from one contributor; the
**format**, since only a month-first locale renders the `en-US` 12-hour shape;
and **proximity**, reported as a lean rather than a verdict. Output:
[`slash_orientation.csv`](assets/slash_orientation.csv).

## Findings

### 1. Only three of seven positions are ever populated

| position | populated values | datasets |
| --- | ---: | ---: |
| `provenance.record_modified[].time` | 5,201,101 | 53 |
| `provenance.record_created.time` | 2,428,291 | 53 |
| `provenance.experiment_start` | 1,977 | 2 |
| `outcomes[].analyses{}.instrument_last_calibrated` | 0 | 0 |
| `inputs{}.…analyses{}.instrument_last_calibrated` | 0 | 0 |
| `workups[].…analyses{}.instrument_last_calibrated` | 0 | 0 |
| `outcomes[].products[]…authentic_standard.…instrument_last_calibrated` | 0 | 0 |

`instrument_last_calibrated` is unset in all 226,316 `Analysis` messages the
corpus contains, and the corpus has no `Analysis` anywhere except under
`outcomes[]`. `experiment_start` — the one field describing the chemistry rather
than the record — is set by 2 of 53 datasets.

A normalizer therefore has three positions to handle, not seven.

### 2. The formats, by position

#### `provenance.record_created.time` — 2,428,291 values, 8 families / 13 signatures

| family | values | datasets | example |
| --- | ---: | ---: | --- |
| `python-str` | 1,771,416 | 5 | `2022-12-02 17:42:01.780701` |
| `slash-24h` | 584,912 | 19 | `18/09/2024, 16:54:56` |
| `iso-T` | 48,498 | 4 | `2025-12-19T10:27:58` |
| `slash-12h` | 20,745 | 21 | `10/19/2021, 12:16:25 PM` |
| `slash-24h` (no comma) | 1,430 | 1 | `18/08/2024 02:10:09` |
| `iso-date` | 1,241 | 2 | `2024-07-30` |
| `ctime` | 48 | 1 | `Thu Jul 18 18:22:17 2024` |
| `python-str` (no microseconds) | 1 | 1 | `2022-12-02 19:09:01` |

#### `provenance.record_modified[].time` — 5,201,101 values, 3 families / 4 signatures

| family | values | datasets | example |
| --- | ---: | ---: | --- |
| `ctime` | 4,678,361 | 53 | `Fri Oct 22 22:19:55 2021` |
| `python-str` | 500,467 | 11 | `2021-03-04 15:28:23.848996` |
| `slash-24h` | 22,273 | 6 | `08/05/2024, 11:34:02` |

#### `provenance.experiment_start` — 1,977 values, 2 families / 2 signatures

| family | values | datasets | example |
| --- | ---: | ---: | --- |
| `iso-T` | 1,227 | 1 | `2025-01-01T00:00:00` |
| `slash-date` | 750 | 1 | `07/01/2008` |

Families collapse field-width variation: `ctime` covers both `Fri Oct 22 …` and
`Thu Mar  4 …` (space-padded day), and the `slash-*` families cover both
`10/19/2021` and `6/2/2021`. That collapse is what turns 15 signatures into 9
families, and it is the right granularity for a parser but the wrong one for
`strptime` — `%d` will not read `Mar  4`.

Each shape names its producer; see finding 5.

### 3. Consistency is the exception

- **15 of 108** populated (dataset, position) cells hold more than one format
  family; **17** hold more than one signature.
- **14 of the 15** are `record_modified`, whose repeated events accumulate one
  entry per tool that ever touched the reaction. `7d8f5fd9`, `b440f8c9` and
  `d319c2a2` carry three families in that one field.
- The exception is `1158e351` (USPTO grants), where a single `record_created`
  out of 1,771,032 is `python-str` without microseconds, which is what
  `str(datetime)` produces when the microsecond field happens to be zero.
- **52 of 53** datasets use different families for `record_created` and
  `record_modified`. The lone exception, `5415f83d`, is `ctime` for both.

Per-dataset detail is in
[`date_time_formats.csv`](assets/date_time_formats.csv).

### 4. `NN/NN/NNNN` is the part that changes answers

41 datasets carry a slash-separated date. Reading the first field as the month
is right for most of them and wrong for some, and the string never says which.

| verdict | datasets | how settled |
| --- | ---: | --- |
| month-first | 35 | 25 by witness, 5 by bound, 3 by format, 2 by submission supplemental data |
| day-first | 4 | 3 by witness (`172039a7`, `3b8a2ef3`, `c5b00523`), 1 by sibling (`2be11f57`) |
| open | 2 | `5c9a1032`, `5e8318f0` |

No dataset contradicts itself: where a dataset writes slash dates at both
`record_created` and `record_modified`, both agree.

`dateutil` gets the 28 witnessed datasets right, because it retries day-first
when the first field exceeds 12. It cannot get the other 13 right except by
luck, and its default is month-first. Four kinds of evidence settle 11 of
those 13.

**Bounds settle 5.** A reaction's `record_created` precedes its own
`record_modified` events, and for `0c75d677`, `3b5db90e`, `675eddca`,
`89b08371` and `d26118ac` the day-first reading lands after that bound — up to
9 days after, for `675eddca` — so only month-first is possible.

**A sibling settles a sixth.** `2be11f57` arrived in
[ord-data#203](https://github.com/Open-Reaction-Database/ord-data/pull/203)
alongside `172039a7` and `3b8a2ef3`, which are day-first by witness, in the same
shape. Its own numbers agree: read day-first, its `record_created` lands 17
hours before the pipeline stamped the reaction — what submission looks like —
against 29 days for month-first.

**The format settles three more.** Every 12-hour value in the corpus matches the
exact `en-US` `Date.toLocaleString()` rendering — unpadded fields, a comma, and
an uppercase meridiem — and no day-first locale produces it: the ones that use a
12-hour clock render a lowercase meridiem. The corpus agrees: of the 21
(dataset, position) cells in that shape, the 18 that other evidence already
settles are month-first and none is day-first. So `46ff9a32`, `4d431564` and
`cbcc4048` are month-first too.

**Two were confirmed from outside the corpus.** Both against the supplemental
data attached to their submission pull requests: `35a5a513` is `1 July 2021`
per [ord-data#86](https://github.com/Open-Reaction-Database/ord-data/pull/86),
and `d9297630` is `6 July 2024` per
[ord-data#188](https://github.com/Open-Reaction-Database/ord-data/pull/188).
Every remaining route runs out inside the corpus, so this is the tier that has
to close the rest.

#### The thirteen that no value in the corpus settles

For the two still open, the **rejected** column holds both readings, month-first
first.

| dataset | reactions | submission | value | decision | rejected | settled by |
| --- | ---: | --- | --- | --- | --- | --- |
| `0c75d677` | 256 | [#57](https://github.com/Open-Reaction-Database/ord-data/pull/57) → [#74](https://github.com/Open-Reaction-Database/ord-data/pull/74) | `2/4/2021, 11:24:34 AM` | 4 Feb 2021 | 2 Apr 2021 | bound |
| `3b5db90e` | 450 | [#97](https://github.com/Open-Reaction-Database/ord-data/pull/97) → [#99](https://github.com/Open-Reaction-Database/ord-data/pull/99) | `6/10/2021, 10:43:43 PM` | 10 Jun 2021 | 6 Oct 2021 | bound |
| `675eddca` | 1,536 | [#174](https://github.com/Open-Reaction-Database/ord-data/pull/174) → [#176](https://github.com/Open-Reaction-Database/ord-data/pull/176) | `8/9/2023, 10:44:35 PM` | 9 Aug 2023 | 8 Sep 2023 | bound |
| `89b08371` | 24 | [#84](https://github.com/Open-Reaction-Database/ord-data/pull/84) → [#87](https://github.com/Open-Reaction-Database/ord-data/pull/87) | `05/08/2021, 10:29:17` | 8 May 2021 | 5 Aug 2021 | bound |
| `d26118ac` | 1,728 | [#57](https://github.com/Open-Reaction-Database/ord-data/pull/57) → [#74](https://github.com/Open-Reaction-Database/ord-data/pull/74) | `2/4/2021, 11:24:34 AM` | 4 Feb 2021 | 2 Apr 2021 | bound |
| `2be11f57` | 1,152 | [#203](https://github.com/Open-Reaction-Database/ord-data/pull/203) | `09/10/2024, 17:25:29` | 9 Oct 2024 | 10 Sep 2024 | sibling |
| `46ff9a32` | 4,312 | [#14](https://github.com/Open-Reaction-Database/ord-data/pull/14) → [#20](https://github.com/Open-Reaction-Database/ord-data/pull/20) | `10/5/2020, 1:49:04 PM` | 5 Oct 2020 | 10 May 2020 | format |
| `4d431564` | 90 | [#93](https://github.com/Open-Reaction-Database/ord-data/pull/93) → [#109](https://github.com/Open-Reaction-Database/ord-data/pull/109) | `6/2/2021, 8:10:58 AM` | 2 Jun 2021 | 6 Feb 2021 | format |
| `cbcc4048` | 288 | [#9](https://github.com/Open-Reaction-Database/ord-data/pull/9) → [#37](https://github.com/Open-Reaction-Database/ord-data/pull/37) | `9/3/2020, 5:11:39 PM` | 3 Sep 2020 | 9 Mar 2020 | format |
| `35a5a513` | 7 | [#86](https://github.com/Open-Reaction-Database/ord-data/pull/86) → [#108](https://github.com/Open-Reaction-Database/ord-data/pull/108) | `07/01/2021, 15:05:35` | 1 Jul 2021 | 7 Jan 2021 | ord-data#86 supplemental data |
| `d9297630` | 39,347 | [#187](https://github.com/Open-Reaction-Database/ord-data/pull/187) → [#188](https://github.com/Open-Reaction-Database/ord-data/pull/188) → [#189](https://github.com/Open-Reaction-Database/ord-data/pull/189) | `07/06/2024, 23:25:41` | 6 Jul 2024 | 7 Jun 2024 | ord-data#188 supplemental data |
| `5c9a1032` | 9,632 | [#212](https://github.com/Open-Reaction-Database/ord-data/pull/212) → [#213](https://github.com/Open-Reaction-Database/ord-data/pull/213) | `08/05/2024, 11:33:06` | **open** | 5 Aug 2024 / 8 May 2024 | — |
| `5e8318f0` | 24 | [#217](https://github.com/Open-Reaction-Database/ord-data/pull/217) → [#218](https://github.com/Open-Reaction-Database/ord-data/pull/218) | `05/12/2024, 15:29:23` | **open** | 12 May 2024 / 5 Dec 2024 | — |

#### The two that stay open

Both write the padded 24-hour `DD/MM/YYYY, HH:mm:ss` shape, and that shape has
two producers that disagree. `Date.toLocaleString()` in a day-first locale emits
it, and an `en-US` browser cannot: `toLocaleString('en-US')` gives
`8/5/2024, 11:33:06 AM`, and even with `hour12: false` the fields stay unpadded.
But `strftime("%m/%d/%Y, %H:%M:%S")` in a submission script emits it too, and
that is month-first. The shape covers 25 (dataset, position) cells, and the 22
that are settled split 19 month-first to 3 day-first, so it decides nothing on
its own.

Neither does the person on the record. The same recorded contributor sits on
both sides of the question three months apart: `record_created` in
[ord-data#203](https://github.com/Open-Reaction-Database/ord-data/pull/203) is
`18/09/2024, 16:54:56`, day-first by witness, while `a12fa15d` carries a
`record_modified` of `12/18/2024, 17:08:03`, month-first by witness, from a
correction pass over 97 of its 288 reactions.

What is left is proximity, which is weak and, for these two, points in opposite
directions:

| | `5c9a1032` | `5e8318f0` |
| --- | --- | --- |
| reactions | 9,632 | 24 |
| submission | ord-data#212 → [#213](https://github.com/Open-Reaction-Database/ord-data/pull/213) | ord-data#217 → [#218](https://github.com/Open-Reaction-Database/ord-data/pull/218) |
| month-first | 5 Aug 2024, 103 d before the bound | 12 May 2024, 252 d |
| day-first | 8 May 2024, 192 d | 5 Dec 2024, 45 d |
| proximity favors | month-first, 1.9× | day-first, 5.6× |
| other evidence | two more `record_modified` events in the same shape, 43 s apart, which reads as a person in a UI — and a browser emitting this shape has to be day-first | none |

`5e8318f0` is the one place in the corpus where the reading in use today is
probably wrong: the only evidence that bears on it points at 5 December 2024,
and `dateutil` reads 12 May. It is 24 reactions.

Both need their submitters asked. Neither should be rewritten until they are.

### 5. Every format traces to a tool, and three of the four are ours

| producer | writes | families |
| --- | --- | --- |
| `ord_schema.updates` | `datetime.now(UTC).ctime()` | `ctime` |
| ord-interface editor (deleted) | a **now** button calling `new Date().toLocaleString()` | `slash-12h`, `slash-24h` |
| ord-app service | `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")` | `iso-T`, less the `Z` |
| contributor scripts | whatever they used, mostly `str(datetime)` | `python-str`, `iso-date` |

The deleted editor is the whole story of finding 4. Its provenance form had a
**now** button — `onclick="$(this).prev().text(new Date().toLocaleString())"`,
on both record creation and record modification — so the stored string was
whatever the contributor's browser locale rendered, in their local wall clock,
with no zone. `toISOString` on that same button would have left all 41 datasets
unambiguous.

ord-app replaced it and does write ISO 8601 in UTC — but the `Z` never reaches
the corpus. The UI round-trips every `DateTime` through
`reactionDateTimeToOrd`, which converts to UTC with `dayjs` and then formats
with `DATE_TIME_FORMAT = 'YYYY-MM-DDTHH:mm:ss'`, a mask with no zone
designator. So the first save through the form strips the marker the service
wrote, which is why the corpus has 48,498 `iso-T` values and not one `Z`.

### 6. Every value is time-zone naive

No signature in the corpus contains an offset, a `Z`, or a zone name. The
`ctime` and `iso-T` values are UTC because their producers make them so, though
neither says as much in the string; the editor-produced `slash-*` values are the
contributor's local wall clock, and their offset is not recoverable from the
record at all.

## Proposal

Normalize every stored `DateTime` to ISO 8601, at the precision the source
carried, with a `Z` only where the corpus knows the zone. Fix the producers
first, then rewrite; in the other order the next submission undoes the rewrite.

[`preview_normalization.py`](assets/preview_normalization.py) is the dry run.
It parses all 7,592,793 values outside the two open datasets with explicit
`strptime` formats and re-emits them, and it fails loudly on anything it cannot
read — so the shape of the proposal is checkable before anyone rewrites 1.2 GB
of LFS objects.

### The target form

Three shapes, because the corpus carries three levels of knowledge:

| shape | when | example |
| --- | --- | --- |
| `YYYY-MM-DD` | the source carried no time | `2008-07-01` |
| `YYYY-MM-DDTHH:MM:SS[.ffffff]` | zone unknown | `2021-03-04T15:28:23.848996` |
| `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` | zone known | `2021-10-22T22:19:55Z` |

Sub-second precision is kept where the source had it; a date-only source stays a
date rather than acquiring a fictional midnight.

### What earns a `Z`

**2,428,294 values, 32% of the corpus** — exactly the `record_modified` events
the submission pipeline wrote, identified by
`person.email == "github-actions@github.com"` together with
`details == "Automatic updates from the submission pipeline."`. Every one of
them is `ctime`, and `updates.py` produces it from
`datetime.datetime.now(datetime.UTC)`, so UTC is a fact about them rather than a
guess.

Nothing else earns one. The other 2,250,115 `ctime` values look identical and
are contributor-written — 1,771,032 of them one maintainer batch edit carrying
`details = "Set is_mined=True for USPTO data."` — and nothing in the record says
which clock produced them. The `iso-T` values are almost certainly ord-app's,
which works in UTC, but "almost certainly" is not a zone.

### Order of operations

1. **`updates.py` writes `isoformat()`.** One line, 4.68M values' worth of
   future output, and the only producer whose zone is known.
2. **ord-app keeps its `Z`.** Widen `DATE_TIME_FORMAT` in
   `ui/src/common/constants.ts` to `YYYY-MM-DDTHH:mm:ss[Z]` so the UI stops
   stripping the marker its own service wrote.
3. **`ord_schema` normalizes on write.** `process_dataset.py --update`
   canonicalizes `DateTime.value`, so a submission arrives canonical whatever
   the contributor's tool produced. Validation *warns* on a non-ISO value rather
   than erroring, so a draft is never rejected for it.
4. **Then rewrite the corpus.** Not before: `process_dataset.py --update` on any
   dataset appends a fresh `ctime` the moment it runs.

### The rewrite

A one-time script in ord-data `scripts/`, with four properties that matter:

- **It reads the day/month order from a table, never from `dateutil`.**
  [`slash_orientation.csv`](assets/slash_orientation.csv) is that table;
  `dateutil` reads `5e8318f0` the wrong way and would freeze the error in.
- **It refuses to touch a dataset whose order is open.** `5c9a1032` and
  `5e8318f0` — 9,656 reactions — are skipped until their submitters answer.
- **It appends no `record_modified` event.** Routing the rewrite through
  `updates.update_dataset` would add 2.4M events to record a formatting change;
  the commit already records it.
- **IDs are safe.** `dataset_id` and `reaction_id` are `uuid4`, not content
  hashes, so nothing downstream re-keys.

Every value parses under one of eight explicit formats — the dry run proves it
over the whole corpus — so the rewrite needs no fuzzy parsing anywhere.

### What it changes

| values | zone | before | after |
| ---: | --- | --- | --- |
| 2,271,884 | naive | `2021-03-04 15:28:23.848996` | `2021-03-04T15:28:23.848996` |
| 2,250,115 | naive | `Fri Oct 18 17:39:39 2024` | `2024-10-18T17:39:39` |
| 2,418,638 | `Z` | `Fri Oct 22 22:19:55 2021` | `2021-10-22T22:19:55Z` |
| 578,265 | naive | `18/09/2024, 16:54:56` | `2024-09-18T16:54:56` |
| 22,405 | naive | `5/17/2023, 6:01:47 PM` | `2023-05-17T18:01:47` |
| 1,430 | naive | `18/08/2024 02:10:09` | `2024-08-18T02:10:09` |
| 750 | naive | `07/01/2008` | `2008-07-01` |
| 50,966 | naive | `2025-01-01T00:00:00` | unchanged |

**7,541,827 values change; 50,966 are already canonical.** Afterwards the corpus
holds three signatures where it holds fifteen today.

### Verification

- **Per value:** reparse the new string and assert it equals the datetime the
  old string denoted under the recorded order.
- **Per dataset:** reaction count and the ordered `reaction_id` list unchanged;
  the multiset of parsed datetimes unchanged.
- **Corpus-wide:** rerun [`scan_date_times.py`](assets/scan_date_times.py) and
  assert nothing outside the three target shapes survives.

### What it costs, and the cheaper thing to do first

Every one of the 51 files changes, so the rewrite writes ~1.2 GB of new LFS
objects, the old ones stay in history, and the Hugging Face mirror re-syncs the
lot. LFS download bandwidth is already ~87% clones and forks.

So: **do steps 1–3 now, and ship a reader before the rewrite.** A
`parse_date_time(value, *, day_first)` in ord-schema, plus the orientation table
beside it, gives every consumer correct datetimes today at no LFS cost and
without freezing the two open decisions. The rewrite then becomes optional, and
can wait until `5c9a1032` and `5e8318f0` are settled and until some other
corpus-wide change is due, so the churn is paid once for several reasons rather
than once for formatting.

### Still open

`experiment_start` needs a definition before it needs a format. Two datasets use
it: `00005539` means it, with 491 distinct dates over 750 reactions, and
`1ec2807f` does not — all 1,227 of its reactions carry the same
`2025-01-01T00:00:00`. Whether the field is worth normalizing depends on whether
it is worth keeping.

## References

- [ord-data](https://github.com/Open-Reaction-Database/ord-data) at
  [`83f971f`](https://github.com/Open-Reaction-Database/ord-data/commit/83f971f)
  — the corpus scanned.
- [`ord_schema/updates.py`](https://github.com/Open-Reaction-Database/ord-schema/blob/main/ord_schema/updates.py)
  — writes the `ctime` values.
- [`ord_schema/validations.py`](https://github.com/Open-Reaction-Database/ord-schema/blob/main/ord_schema/validations.py)
  — `_validate_date_time`, the only constraint on the field today.
- ord-interface `ord_interface/editor/html/reaction.html` at
  [`d5e6981^`](https://github.com/Open-Reaction-Database/ord-interface/commit/d5e6981)
  — the **now** button, removed with the editor in ord-interface#172.
- ord-app `ord_app/service_api/domain/reactions.py` and
  `ui/src/common/constants.ts` — the service's `Z` and the UI mask that drops
  it.
- [`assets/README.md`](assets/README.md) — how to reproduce the extracts and
  the normalization dry run.
