# Row accounting: release c94bfedc to 448651e7

Measured 2026-11-01 at 3df9bdf6 for ct-qg8e, ct-opy0 and ct-db3w. Nothing here was repaired or published.

**Result:** every row change in all 19 manifest files is sized, but not every cause is established, so `release_diff.py` exits 1 on this pair. The JSON's `failing` list names each group whose cause was not checked or is a defect, and "Still open" below covers the same gaps. The largest change is a regression: archive members stopped being real files (D1). No rebuild has run, so D1's causation is strong correlation, not proof.

`release_diff.py` is a diagnostic, not a gate, and is not in the publish path. Its group sums are close to an identity, and the `list` sum always is, so a matching sum shows only that no row was dropped.

## Inputs and commands

| Input | Size | SHA-256 |
|---|---|---|
| `publish_v20/model/evidence/capture_sources.parquet` | 471,549,010 | `d5a98cf46e189d95f03f6929392bb70412aa1b9eebdc1b96937db53da2bb4ed0` |
| `publish_v21/model/evidence/capture_sources.parquet` | 474,908,455 | `e7a0ed94f186525ccf537dd7e305ee3c0e11f5cb4e8657a62da251bd8b21b145` |
| `publish_v21/inputs/captures.parquet` | 183,348,987 | `92c2da92d9c8436a3b3e937485f46e344c98ffd36bdacf9face6f2baa0399bcc` |

These paths are machine-local, in another session's temporary directory, and may vanish. The public pointer named 448651e7 with previous c94bfedc when checked. Downloaded files matched their manifests; `members`, `rosters`, `nominations` and `url_variants` were not downloaded, and their digests are identical across the releases.

The command later moved into the publisher (2026-11-02); its numbers here are unchanged. The original was
`scripts/measure/release_diff.py --prev PREV --live LIVE --evidence-prev … --evidence-live …`.

```
.venv/bin/python -I -m viewer_publication.release_comparison --base PREV --candidate LIVE \
  --evidence-base V20_CAPTURE_SOURCES --evidence-candidate V21_CAPTURE_SOURCES --record-digest CAPTURES \
  --removed-keys docs/measurements/release-diff-c94bfedc-448651e7-removed-link-keys.csv.gz \
  --output docs/measurements/release-diff-c94bfedc-448651e7-20261101.json
.venv/bin/python -I docs/measurements/release-diff-c94bfedc-448651e7-verify.py DOWNLOADS BUILD docs/measurements/release-diff-c94bfedc-448651e7-20261101.json
DOCSPEC_JOB_CONFIG=... .venv/bin/python scripts/dev.py test production-offline --path packages/viewer_publication/tests/test_release_comparison.py
```

The verifier uses pyarrow with no SQL and asserts against the JSON by other routes: Parquet footers for deltas, capture real-file sets instead of flips or links for removed keys, and bodies instead of link keys for splits. It exits 0. **The bodies route gives 60,630 split rows against 60,616 by link key; the gap of 14 is unexplained** and pinned in the script. Compared row by row, 18 rows differ (+16, -2), all PDFs:

- Body route higher: previous rows 48603, 49194, 49304, 49305, 58931, 59615, 59881, 337427 (1 link-key row, 2 by body) and 145824, 145849, 145856, 145922, 145944, 145969, 146012, 146015 (2 and 3).
- Body route lower: 73315, 81344 (4 and 3).

About 4,000 bodies sit on several live rows, so the route counts distinct holder sets, which needs no tie-break. Counting every holder gives 70,747, and an earlier tie-breaking version gave a gap of 12 on 16 rows; both depended on how those shared bodies were handled. An earlier pass found all 19 files in each release match the build's own copy, which comes from the same pipeline.

## Reconciliation

| File | Delta | Groups |
|---|---|---|
| `list`, `detail` | +60,509 | split +60,616, all from rows with a member source (7,700×1, 26,455×2, 2×3; 34,157 documents); merged -22; removed -112 (71 top-level, 41 member); added +27 |
| `links` | -7,235 | member-only bodies -7,194; top-level bodies -72; newly eligible +31 |
| `sources` | -68,771 | members -68,785; NULL URL +72 (D2); URLs gone -2; new URLs +14; same-URL removed -72; same-URL added +2 |
| `urls` | -1,076 | keys gone -639 (545 keys); new +14; fewer rows -453; more rows +2. The full histogram is in the JSON |
| `url_state` | -2,919 | oEmbed scope exclusion -2,940; queued links with no attempts +21 |
| `bills` | +1,402 | all are new meeting subjects; 0 removed |
| `witnesses` | +840 | only previous -591 (2 on gone occasions, 589 on kept); only live +673 (604 on 149 new occasions, 69 on kept); repeated occurrences +758 |
| `recordings` | +5 | 5 new keys with empty `event_ids`; 0 removed |
| `meetings`, `recoveries` | 0 | same keys, new bytes |

Digest-identical: `committees`, `members`, `nominations`, `rosters`, `url_variants`.

### The 7,194 versus 7,266 gap

The independent count of 7,266 removed link keys is right. The earlier 7,194 counted only member-only bodies. The other 72 are top-level bodies whose capture attempt lost eligibility under ct-sh4j:

| v20 to v21 outcome of the attempt | Keys |
|---|---|
| `stored` to `request_failed` | 67 |
| `stored` to `failed`, HTTP 403 | 3 |
| `stored` to `failed`, HTTP 500 | 1 |
| `stored` to `failed`, HTTP 404 | 1 |

Every removed key has a matching flip, as does every one of the 31 added keys. The 72 same-URL rows are the same event: all sit on the top-level-removed documents (70 of the 71 rows, none with a member source). The 72 NULL URLs are a separate group, and that count matching is a coincidence.

### Groups the first pass left open

- **Merged live rows (20 rows, -22):**
  - 15 Senate Finance rows joined a recovery row through a `&download=1` address: `download-ampersand-query`.
  - 2 Finance rows (`drug-pricing...part-iii`, `nominations-of-kipp-kranbuhl...`) had three spellings of one address, which need that rule and `senate-coldfusion-download`.
  - 2 `docs.house.gov` PDF and XML pairs became valid publisher renditions after a competing PDF row left through an attempt-1 flip.
  - 1 Aging row is a likely false merge (below).
  - These assignments come from rule text and evidence rows. The rules were not re-executed.
- **Removed and added rows:** all 112 and all 27 tie to flips by key.
- **Same-URL sources:** all 72 removed rows sit on removed documents (70 rows, 71 URLs). The 2 added rows come from new real pages on `help.senate.gov`.
- **URLs gone:** the 2 `sciencedirect.com` addresses left with flipped bodies `1B733F11...` and `38D0BDAB...`. The address is the `http` request spelling, so a match on `url` misses it.
- **New URLs:** all 14 tie to not-real-to-real flips, 13 on new rows and 1 on row 182387.

### Field changes on matched rows

- `meetings`: `session` 6,157; `transcripts` by `package_id` 9,249; `subject_keys` 1,172; `title` 686; `committees` 85; `meeting_type` 3; `sittings` 3.
- `list`, 332,697 one-to-one rows: `witness_keys` 38,744; `title` 5,385; `version_keys` 565; `filename` 43; `document_date` 31; others in the JSON.
- `detail`, same rows: `src_len` 542; `facts` 56; `alternates` 55; `saved_body` and `link_key` 17; `package_id` 13.

### `url_state` scheduling fields

The `url_state_lines`, `url_state_good_lines` and `url_state` SQL all changed between v20 and v21.

| Field | Changed | Cause |
|---|---|---|
| `last_outcome` | 34,664 | failed to stored 34,598 (34,584 match the new `context_good` rule, 14 do not); unchanged to stored 61; stored to failed 5 |
| `last_status` | 5,437 | all NULL to a value (5,433 to 200) |
| `last_good_at` | 62,934 | `context_good` 34,932; the stored-with-no-status clause 27,945; neither 57 (unclassified) |
| `next_attempt_at` | 10,205 | see below |

`next_attempt_at` moved earlier on 10,202 keys and later on 3, with `last_attempt` unchanged on all. 10,201 are `govinfo.gov` `CHRG-*.zip` URLs; the shifts are -358 days (9,301), -21 days (901) and +358 days (3). **As of 2026-11-01, 10,199 URLs are newly due and 3 are no longer due.** The likely cause is that a split-off ZIP row has no meeting, so its age is unknown and the shortest interval applies. The public files support this directly: of the 10,204 changed URLs that appear in `sources`, 10,202 sat on meeting-linked documents in the previous release and 2 do in the live one. The chain through the unretained meeting dates is still inferred from the SQL.

## Consumer impact

Measured from the public files.

| Area | Measured | Note |
|---|---|---|
| Scheduling | Interval 365 to 7 days on 9,301 URLs, 28 to 7 on 901, 7 to 365 on 3 | The 10,202 URLs now on 7 days have 84.3 GB of saved bytes. **Recurrence is inferred:** about 84 GB weekly if capture-archive follows these intervals and they do not settle |
| Transcripts | **8,064 events are newly duplicated: events with duplicate transcripts went 3,199 to 11,263.** Entries 20,531 to 32,882 on about 16,470 distinct `(event, package)` pairs | 9,248 of 9,249 changed events keep the same package set and now hold duplicates. `HearingDetail.tsx:172` maps entries without deduplicating, so a hearing lists a transcript repeatedly. The other change is event 336500, which lost `CHRG-119shrg58631` |
| Search | `published-hearing` rows 78,603 to 138,980; 34,019 live rows titled "ZIP" with no meeting or date | **The title is not new.** The previous release had 34,184 rows titled "ZIP", 33,842 of them PDFs and 23,934 with no meeting or date. What changed is that these rows are now separate ZIP documents: ZIP-titled rows with a meeting went 10,250 to 0 |
| Identifiers | 0 of 147,048 `witness_key`s survive; 7,266 link keys no longer resolve | `archive.ts:238-241` returns null for a missing key. Neither change has a published mapping |
| D2 | 12 documents have only a NULL address; 31 NULL rows that hold the row's saved body have `is_saved` false | §7.10 requires `is_saved` true on each address of the saved file. The 32nd false row, on 409584, holds a non-saved body |

## Defects

**D1, needs an owner decision: archive members stopped being real files.** All 171,894 member rows in the input have `complete` NULL, and 68,785 member capture rows flipped from real to not real. Valid publisher rendition groups fell from 35,936 to 1,726, the likely mechanism of the split. Member rows in `sources` went from 68,785 to 0, and every split row had a member source. Removed keys are listed by cause in `release-diff-c94bfedc-448651e7-removed-link-keys.csv.gz`.

The documents conflict, and that is the owner's call. §6.1 (line 243) says a member does not borrow the final-response derivation, which is what ct-sh4j implemented. §7.3 (line 476) still assumes real members: "34,331 HTML members sit at good-fetched ZIP URLs". A blanket restore would also be wrong: 12 of the flipped members are HTTP 206. The owner has indicated that a ZIP is capture transport rather than a document; that framing is pending, not decided, and this file does not assume it.

"Members alone cause the split" stays unproven until a rebuild compares them, and this work has no engine slot for one.

**D2: `sources.url` NULL on 72 rows.** The chain, now traced:

1. 72 `source_id`s in v21 evidence have a real capture and also a stored capture with NULL `context_url`. v20 has 0.
2. These sources became real when `http_status` moved from NULL to 200 under ct-sh4j.
3. `document-addresses.sql` requires only that the member is real, so it keeps the source's other context rows, including the NULL one.

71 of the 72 are the row's saved body; the other (source `a88f423a`) is a non-saved body on row 409584.

**Likely false merge.** Row 421951 now joins O'Malley's testimony and an unrelated Coss document. The hearing page's list item links "Testimony_O'Malley 03.20.24.pdf" to the Coss address, and the new URL rule lets that link resolve. Publisher error is the likely origin; the merge still needs a decision.

**Empty caption tracks.** The tracks on `youtube:Mv5g5Bn4AD8` (new) and `youtube:R0h33K7rw7Q` (changed) have body `e3b0c442...`, the SHA-256 of empty input. The source returned nothing; see the correction above.

## Root causes, from raw receipts and bodies

Read in full from the local mirror, with public bodies where the mirror lacks them. No engine job ran. **Proven** means shown on raw records for the whole set. Comparisons with v20 use public v20 files plus measurements taken before a machine crash wiped the v20 build evidence; v20 row states cannot be re-read.

### D1: raw facts on every affected member row

**All 68,785 affected rows were read, and the raw record contradicts ineligibility on every one.** They sit on 34,323 ZIP receipt lines.

| Raw fact | Rows |
|---|---|
| ZIP `complete` true, `outcome` saved, `archive_processing.status` completed | 68,785 |
| Member entry `status` completed, with no `error_type` | 68,785 |
| Member entry's digest and path match the captures row | 68,785 |
| Member entry has its own `complete` field | **0** |
| ZIP HTTP 200 / HTTP 206 | 68,773 / 12 |

So the members were not lost through failed captures. The receipt format never recorded member completeness, `captures.py:433` keeps that absent value for non-top-level entries, and `good-fetches.sql` requires `complete`. **Eligibility is proven to fail on the missing field and on nothing in the raw record.** The split's dependence on those rows is still not rebuild-tested.

Facts for the owner's decision:

- **HTTP 206:** the 12 rows sit on 6 ZIPs of 794 MB to 1.07 GB. Their receipts have no `content-range` header, yet expansion completed.
- **Raw `mode`:** 238 rows are `retained_import` and 2 `replay` in the raw record, while the captures table says `fetch` for all.
- **Not read:** ZIP bytes. All 34,323 ZIP bodies and 68,779 of the member bodies are absent from the mirror, so these facts are the receipts' own statements, and archive integrity was not re-tested.

### Other sets

| Set | Records read | Result | Status |
|---|---|---|---|
| `url_state` +21 | 1,349,139 reading rows; hit bodies confirmed raw | **21 of 21 are links on raw bodies.** 13 are on two listing pages, `intelligence.house.gov/event-category/meetings/page/3/` (`6324e3ed`, 12 URLs) and `.../category/press-releases/page/34/` (`b0fe3f4c`, 1), which are good but not real files. 8 are on newly real pages (`archive_url_state.py:109`) | Proven links. That those pages were newly good rests on the v20 flip measurement |
| 2 recordings | Same scan; 6 hit bodies each, raw | `6xt7nTuO85A` and `f1J38FlDKxo` are links on 6 Facebook video pages captured through a provider (`221da9b3`, `383235d8`, others). No meeting record lists them, so `event_ids` is empty (`archive_model.py:706`). Whether they are the hearing's video or page furniture was not judged | Proven source |
| 57 `last_good_at` | 98 capture rows on 76 raw lines | Every URL has a row passing the good predicate, and on 55 its `retrieved_at` equals the live value. 40 passing rows have a provider body with no top-level status, and take 200 from the reference | Proven. See the 202 defect below |
| Witnesses -591 | 626 record bodies, all readable | 317 link words such as "download general" and 216 name-like strings are in raw as text but are no longer parsed as these names (205 only as scattered tokens, such as a name joined to a role). 56 are moved meetings. 2 have no live record | Proven as parser corrections, except the moved meetings |
| Witnesses +673 | Same | All 673 are in raw: 592 as a whole name, 81 by tokens. All 167 of their records were captured before the v20 build | Proven real and not newly captured. **Why v20 lacked them is not proven**, because the v19 parser input was lost in the crash |
| Witnesses +758 | Earlier query on live rows | All in the same record as their pair; v21 keeps each occurrence (`appearance-records-resolved.sql:276`) | Proven |
| Moved meetings, 17 events | 34 raw MODS records | See below | **Defect** |
| 34,593 ZIP intervals | 115,760 raw lines | See below | Proven for 34,124, 469 unexplained |

### Defects these reads found

- **Witnesses from the wrong hearing.** All 17 events link two or three transcript packages. `single_package_meetings` (`appearance-records-resolved.sql:107-111`) checks only that a package has one event, not that an event has one package, so one record wins for the event. Comparing each raw MODS title to the meeting title: v21's choice is better on 8, **worse on 3 (100202, 101167, 335827)**, and tied on 6, several with neither package matching (100540 "Fulfilling the Good Friday Agreement" has Syria and Hezbollah packages). Adjacent jacket numbers suggest the event-to-package links themselves are wrong. Title overlap is a rough test.
- **HTTP 202 counted as good.** 23 capture rows have raw `outcome` `http_error` at HTTP 202, yet are `stored` in the table and pass the good predicate, because it accepts 200-299.

### Correction: no real captions are hidden

An earlier version of this file called the two empty tracks a defect that hid real captions. **That was wrong.** The two provider responses thought to be the real captions are JSON wrappers whose whole body has `statusCode` 200 and `httpResponseBody` empty. The direct rows are 0 bytes on raw read. The source returned nothing, so the tracks state an empty capture accurately. What remains open is whether an empty track should be published: 5 recordings carry them, 3 from before this release. ct-sh4j's status change is still why these two appeared (`archive_model.py:728`).

### Does the interval shift recur weekly?

**The code path recurs; the load is not happening today.**

- **Path, proven by code:** a URL with no meeting date has NULL age, so all three registry bands match and the shortest, 7 days, wins (`archive_url_state.py:60`). `next_attempt_at` is the last attempt plus that interval (`model/sql/url-state.sql:10`). The scheduler treats due rows as eligible (`capture_scheduler.py:521`), and `CHRG-*.zip` URLs are in the `documents` scope. Age stays NULL after a refetch, so the URL comes due again.
- **Not running:** `capture-archive.yml:19` requires `ARCHIVE_CAPTURE_ENABLED`, which `gh variable get` did not find, and the workflow has 0 runs. These ZIPs were last fetched in bulk on 2026-10-05 and 10-06, with 123 on 10-16.
- **Whole-set check:** every one of the 34,593 live ZIP URLs is on 7 days with no meeting date. In the previous release, 23,929 had no date and 7 days, 9,300 had age at least 731 and 365 days, and 895 had age 31-730 and 28 days, exactly the registry bands, computed from public meeting dates. **469 had a date through `list.meeting_keys` and 7 days anyway; those are unexplained**, since the model's date path differs from `meeting_keys`. On raw lines, `last_attempt` matches the latest `retrieved_at` on 34,565; 28 of the others are `request_failed`.
- **Load if enabled:** the 84 GB is not the whole weekly set. 24,398 `CHRG-*.zip` URLs were already on 7 days in the previous release, so all 34,593 are now on 7 days and already due, 183.5 GB across the 34,019 with a saved row. D1 added about 10,195 of those URLs. Actual volume is capped by `ARCHIVE_CAPTURE_REQUEST_BUDGET` and `ARCHIVE_CAPTURE_BYTE_BUDGET`, and state moves only when a new release publishes. Whether the fetch is conditional was not checked.
- **Meeting link, proven by code and public files:** the meeting-date union joins through `component_meeting_links` (`archive_model.py:684-692`), and the changed URLs on meeting-linked documents went 10,202 to 2.

## Bug analysis: cause, recurrence, right layer, why it was missed

Analysis only; nothing here is fixed. Read from raw data and `git log`, with no engine job. "Should have been addressed" names a layer, not a chosen fix.

### D1: member eligibility

- **Cause:** `bc0a146c` (2026-11-01, ct-sh4j) added `CASE WHEN NOT top_level THEN e_complete` at `captures.py:433`. Before it, `recorded=first('e_complete', CASE WHEN attempt=0 THEN both('complete') END)` gave members the container's `complete`. No receipt ever stated member completeness, so removing the borrow left NULL on all 171,894 rows, and `good-fetches.sql` requires `complete`. The rule "an unknown prior response or archive member does not borrow" entered §6.1 in `87dc8905`, committed in the same second as the code. The doc followed the code in one change, so nothing reviewed the rule separately.
- **Why the criterion was not enforced:** "Reconcile changed document eligibility by cause on retained inputs before live publication" appears once in ct-sh4j, as text. No note reports a reconciliation. The validator's FAIL list (10:39) and the swarm's PASS (12:05) cover joins, slots, outcome conflicts and test counts, and none mentions it. Acceptance was checked by running tests and reading code, and a release diff was never a required artifact. The criterion also lists archive-member test coverage, and the `bc0a146c` test diff adds no member case.
- **Recurs:** 242,293 top-level stored rows also have NULL `complete` and so fail the same predicate; whether v20 passed them was not measured. Members still carry the container's `http_status` and `outcome`, and `mode` says `fetch` where the raw says `retained_import` or `replay`, so the row borrows some facts and not others.
- **Should have been addressed:** in the data model before code: §6.1 (line 243) against §7.3 (line 476), which needs real members. Then a before-and-after comparison at the capture layer.
- **Why missed:** `capture_comparison.py:42` has listed `complete` as `not_compared` since `f539c2a0` (2026-10-27). `capture_backfill_guard` checks domain, and NULL is in-domain (AGENTS.md says so). Model invariants test one build's internal consistency, never a change against the previous release.

### D2: NULL `sources.url`

- **Cause:** `document-addresses.sql` (`068f2a40`, 2026-10-27) tests that a member is real, then takes every context row of that `source_id`, including non-real rows with NULL `context_url`. `bac12c1f` and `a7f55959` touched the query without changing this. It was latent until `bc0a146c` made 72 such sources real.
- **Recurs:** `source_input` filters NULL only inside its `compatible` branch, and its `RIGHT JOIN addresses` lets the row out. Empty `list.filename` is a related symptom, 2,856 to 2,901 rows.
- **Should have been addressed:** the query's filter at the source grain, and a non-null declaration on the file.
- **Why no check stopped it:** §7.10's table marks `url` as not nullable, but `release-schema.json` has no `nullable` on any `sources.parquet` column. `archive_schema.py:90` reads that key only to refuse a nullable primary key, and `url` is not part of the identity. So nothing checks it at write time, spec and registry disagree, and no invariant found in `archive_model.py` tests it.

### HTTP 202 `http_error` rows

- **Cause:** all 23 are AWS WAF responses. Of the 29 stored, complete 202 rows in the corpus, the 23 with raw `http_error` at 202 all carry `x-amzn-waf-*` headers, 9 of them with empty bodies, on `reliefweb.int`, `fas.org`, `www.un.org` and `www.europarl.europa.eu`. Raw `outcome` is `http_error`, mapped to `failed` at `captures.py:21`. The `BETWEEN 200 AND 299` rule dates from `91254080` (2026-10-27), then `e31aeb42` and `bc0a146c`. Only 429 and 503 are singled out, not 202 as a challenge. impl-d-jobs, on one line, finds HEAD gives attempt 0 `failed` and attempt 1 `stored`, while v21 has attempt 0 `stored`, and **none of the four mapping states it tested reproduces v21**. So the exact v21 path is unproven, and which code built the v21 captures is an open question. Its full re-stage is still running.
- **Recurs:** the same 2xx test is in `good-fetches.sql`, `archive_model.py:728`, `appearance-records-resolved.sql:58` and `archive_url_state.py:28`.
- **Should have been addressed:** `captures.py`, the one owner of attempt outcomes, by keeping a recorded failure and treating a challenge as not a body.
- **Why missed:** HTTP status class stands in for "a document arrived". `page-signals.json` has a `visible_challenge` rule, but it reads body text, so a header-only challenge or an empty body passes it. A WAF case does not appear in `test_captures_final34.py`.

### 17 moved meetings

- **Cause:** `single_package_meetings` (`959c23ee`, 2026-10-30, `appearance-records-resolved.sql:107-111`) asks whether a package has one event, never whether an event has one package. `ranked_source_observations` (`:206`) keeps one record per occasion and source, so one package's witnesses stand for the event. The ranking and link SQL both changed between v20 and v21 (`ab543cef`), which is the inferred reason these 17 moved. The parser output for all 17 Congress.gov records lists 2-3 jackets; **those raw bodies are absent from the mirror and 404 publicly, so the source's own list was not read.**
- **Recurs:** 3,718 live events link two or more packages. 86 of them have MODS witnesses, so 86 are exposed, not just the 17.
- **Should have been addressed:** the occasion identity in the data model: whether a MODS witness belongs to a package or an event.
- **Why missed:** invariants test that keys resolve, and a wrong hearing's witness resolves fine. The review compared counts, and the 17 moved without a count change at event level.

### Transcript duplicates

- **Cause:** `transcripts` has one entry per list row, not per package (`959c23ee`, ordered since `844fba03`). Every entry has a distinct `list_row`; the repeats are the PDF and HTML rows of one package. So these are row-level entries that read as duplicates, and D1 multiplied them by splitting documents. 3,199 events had them before v21, on rows the grouping had not joined.
- **Recurs:** `HearingDetail.tsx:172` maps entries without grouping. Any consumer that reads `transcripts` as "this event's transcripts" gets repeats.
- **Should have been addressed:** the model decision of what an entry is, then the export or the viewer.
- **Why missed:** the schema allows it (`package_id`, `list_row`), and nothing states how many entries one package may have.

### "ZIP" titles

- **Cause:** the title rule (data model line 574, spec `8c33a85a`, 2026-10-26; code `068f2a40`, 2026-10-27) falls back to the earliest listing link's text. On `www.govinfo.gov`, that text is "ZIP" for the package link. Every titled row has a source whose `link_text` is "ZIP": 34,184 and 34,019. The earlier title sat on 33,842 PDFs because member grouping carried the ZIP's address onto the PDF document.
- **When it started:** in all 4 reachable releases: `0db23484` and `a06e2a63` show the same 34,184, as does `c94bfedc`. **No older release could be reached, so the first appearance is not known**; it can be no earlier than the 2026-10-05 ZIP fetches and `068f2a40`.
- **Recurs:** other short titles in the live release: "ZIP" 34,019, "PDF" 3,743, "XML" 198, "here" 50, "Email" 38, "Rules" 4.
- **Should have been addressed:** the title rule, since link text says what a link does, not what a document is. Page-signal vocabularies filter error words but not generic link words.
- **Why missed:** no check found looks at a title's value, only whether rows and keys are consistent.

### Shared pattern

**Every layer checks one build against itself, and none asks whether a value is right against raw or against the last release.** Six defects passed because each check was satisfied by an in-domain value: NULL `complete`, a 2xx status, a resolving key, a present title. Three other threads run through them:

- A criterion written in prose has no owner or artifact that would fail, as with ct-sh4j's reconciliation.
- One property is defined in several places without a single owner: 2xx good, nullability in spec and registry, and the meaning of a member or transcript entry.
- Spec text was changed to match code in the same commit, so the spec could not catch the code.

## Still open

- **Unexplained:** why v20 lacked the +604 witnesses' records; 469 prior ZIP intervals; 18 rows between the split routes.
- **Not readable:** ZIP bytes and most member bodies (absent from the mirror); v19 and v20 build evidence (lost in the crash). The 3 `receipts/pipeline-data/2026-10-28/*` receipts missing from the mirror were not needed by these sets.
- **65 of the 758 extra occurrences** look like documents rather than people, such as "prepared statement on h.r. _" going from 1 to 7.

## ct-opy0 and ct-db3w on 448651e7

Both are unchanged by this release. The comparison ran with explicit pins, and `inputs.archive.release_id` is 448651e7 in both outputs.

| Check | fbf53579 | 37a6ebd4 |
|---|---|---|
| `rows.committee_meetings` | 6,098 | 6,099 |
| House missing | 117688 | 117688, 119588 |
| Senate missing | 335202, 335760, 335780, 337725, 338764, 338786 | same |
| `archive_chamber_null` (House / nochamber) | 1 / 71 | 1 / 71 |
| Archive NULL chamber | 713 rows: 72 matched, 95 before window, 547 no date; 119583 is in both the matched and no-date counts, so these sum to 714 | same |

- **Correction to ct-opy0:** the House row with NULL archive chamber is event 119583, not 117688, which is absent. Dated NULL-chamber rows are 166: 165 have joint codes (`jcse00` 116, `jjec00` 40, `jslc00` 4, `jspr00` 4, `jsec00` 1), and 104064 has `ssga00` and `hshm09`.
- **The seven:** all absent from `meetings.parquet` and `meeting_records`, with 0 exact-number matches in `url_state` or captures. Bare substring hits exist for 117688 (6 in `url_state`, 17 in captures) and 335202 (1 and 3); the samples inspected were other numbers, such as `BILLS-1176880ih`, and the exact-number search confirms this.
- **119588:** new since the tickets, dated at the window end, 2026-11-13, and also has 0 matches. Its "Scheduled" status is the planner's reading, not re-read here. It is not one of the seven.
- **The 547:** 0 in `meeting_records`. Substring and exact-number searches both hit all 547, so they cannot discriminate. By URL position, 546 appear only in `docs.house.gov` document paths. The other is 119583, the matched row above: it has a congress.gov document path and the only record-bearing address (`ByEvent`), which is in `url_state` with no capture. So 546 events have no record-bearing address at all.

The helper crashes on D2 and, run with no arguments, silently reports its `bound` pin c94bfedc. This wrapper called it without editing spicy-regs:

```python
pins,paths=m.inputs(Path(f'{P}/spicy-cache'),json.load(open(f'{P}/pin-{k}.json'))['inputs'])
n=duckdb.execute(f"select count(*) from read_parquet('{paths['sources']}') where url is null").fetchone()[0]
f=Path(f'{P}/sources-nonnull.parquet')
duckdb.execute(f"copy (select * from read_parquet('{paths['sources']}') where url is not null) to '{f}' (format parquet)")
paths=dict(paths); paths['sources']=f
r={'inputs':pins,'excluded_null_sources_url':n,**m.compare(paths)}
```

## Counterfactual: not run

The control rebuild was stopped before it finished, because free disk (14 GiB) was below the 30 GiB floor set for this machine. No overlay ran. Option (a) for D1 is therefore unsized, and whether HEAD reproduces the v21 row counts is unknown. An earlier attempt failed under the default 4 GB spill limit and needs the v21 limits file.

## What these checks cannot see

- **Link-key matching** cannot see a one-to-one row whose content got worse, or match a document with no surviving key.
- **Flips** do not show v20 was right. v20's `complete = true` on members was itself borrowed. 17,254 input rows never reach `capture_sources` in either build, and this comparison cannot see them.
- **`release_diff.py` statuses:** `verified` means a stated check passed, such as a key matching a flip while its body is no longer real, or a bill matching a meeting subject new to this release. Field changes on matched rows are reported but fail only for wiped subject keys. It does not mean the row is right or that the cause is the only one.
- **The verifier** reads the same published files, and its hard-coded public counts were first measured in this work, so they catch later change rather than prove the first reading.
- **Hash checks** show consistency, not truth.
- **The spicy-regs comparison** reports only what its queries project, with 72 rows removed. Its `lookup_key_self_check` is self-referential, and its table is a moving window.
- **Viewer effects** were not measured.
