# Date and time formats across the corpus

- **Date:** 2026-09-03
- **Author:** Steven Kearnes
- **Status:** final
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
value settles it — 25 month-first, **3 day-first**. Bounds from the reactions'
own `record_modified` events settle 5 more, and one submission's co-submitted
siblings settle a sixth, for **34 settled: 30 month-first, 4 day-first**.
`dateutil` reads the **7 undecidable** ones month-first, and one of those —
`5e8318f0` — leans the other way.

**Nothing carries a time zone.** Not one of the 7,631,369 values has a UTC
offset or a zone name — including the 48,498 that ord-app's service writes with
a `Z`, which the UI strips on the contributor's first save.

Four of the schema's seven `DateTime` positions are never populated at all.

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
versus month-first from four kinds of evidence, strongest first: a **witness**
value whose first field exceeds 12 (day-first) or whose second does
(month-first); an **upper bound**, since a reaction's `record_created` precedes
each of its own `record_modified` events and no value can postdate the last
commit to touch the dataset; a **sibling**, since datasets added by one commit
are one submission from one contributor; and **proximity**, reported as a lean
rather than a verdict. Output:
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
| month-first | 30 | 25 by witness, 5 by bound |
| day-first | 4 | 3 by witness (`172039a7`, `3b8a2ef3`, `c5b00523`), 1 by sibling (`2be11f57`) |
| month-first (lean) | 6 | proximity only |
| day-first (lean) | 1 | proximity only (`5e8318f0`) |

No dataset contradicts itself: where a dataset writes slash dates at both
`record_created` and `record_modified`, both agree.

`dateutil` gets the 28 witnessed datasets right, because it retries day-first
when the first field exceeds 12. It cannot get the other 13 right except by
luck, and its default is month-first.

**Bounds settle 5.** A reaction's `record_created` precedes its own
`record_modified` events, and for `0c75d677`, `3b5db90e`, `675eddca`,
`89b08371` and `d26118ac` the day-first reading lands after that bound — up to
9 days after, for `675eddca` — so only month-first is possible.

**A sibling settles a sixth.** `2be11f57` arrived in
[ord-data#203](https://github.com/Open-Reaction-Database/ord-data/pull/203)
alongside `172039a7` and `3b8a2ef3`, which are day-first by witness, in the same
`slash-24h` shape. Its own numbers agree: read day-first, its `record_created`
lands 17 hours before the pipeline stamped the reaction — what submission looks
like — against 29 days for month-first.

**One lean disagrees with `dateutil`.** `5e8318f0` (24 reactions) writes
`05/12/2024, 15:29:23` against a bound of 2025-01-20; month-first puts creation
252 days before submission, day-first 45. Nothing in the corpus proves it.

The other six leans agree with what `dateutil` already does. They are unproven,
not wrong.

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

## Conclusions / next steps

1. **Normalize on write, in ord-schema, not here.** Every format in the corpus
   traces to a tool, and three of the four producers are ours. Making
   `DateTime` normalize to ISO 8601 at validation time stops the growth even
   for the fourth; a corpus rewrite is a separate, one-time job.
2. **Decide the 7 undecidable datasets before rewriting anything.** A rewrite
   freezes `dateutil`'s month-first guess into the data and destroys the
   evidence that it was ever a guess. `5e8318f0` is the one that disagrees with
   that guess and should be confirmed with its submitter.
3. **`ctime` is the cheapest fix and the biggest one.** One line in
   `updates.py` moves 4.68M values — 61% of the corpus — from a C-runtime
   format with no zone to `datetime.datetime.now(datetime.UTC).isoformat()`,
   which would state the zone the value already has.
4. **Keep ord-app's `Z`.** The service already writes it and
   `DATE_TIME_FORMAT` in the UI throws it away, so a zone-anchored value
   becomes a naive one on the contributor's first save. Widening that one mask
   to `YYYY-MM-DDTHH:mm:ss[Z]` is a smaller change than anything else here and
   it is the only fix that stops new naive values from being created. The
   `toLocaleString` problem that produced finding 4 is already gone with the
   editor.
5. **`experiment_start` needs a definition before it needs a format.** Two
   datasets use it. `00005539` means it — 491 distinct dates over 750
   reactions — and `1ec2807f` does not: all 1,227 of its reactions carry the
   same `2025-01-01T00:00:00`. Whether the field is worth normalizing depends
   on whether it is worth keeping.

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
- [`assets/README.md`](assets/README.md) — how to reproduce the two extracts.
