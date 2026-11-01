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

```
.venv/bin/python -I scripts/measure/release_diff.py --prev PREV --live LIVE \
  --evidence-prev V20_CAPTURE_SOURCES --evidence-live V21_CAPTURE_SOURCES --record-digest CAPTURES \
  --removed-keys docs/measurements/release-diff-c94bfedc-448651e7-removed-link-keys.csv.gz \
  --output docs/measurements/release-diff-c94bfedc-448651e7-20261101.json
.venv/bin/python -I docs/measurements/release-diff-c94bfedc-448651e7-verify.py DOWNLOADS BUILD docs/measurements/release-diff-c94bfedc-448651e7-20261101.json
DOCSPEC_JOB_CONFIG=... .venv/bin/python scripts/dev.py test production-offline --path scripts/measure/tests/test_release_diff.py
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

**Empty caption tracks.** The tracks on `youtube:Mv5g5Bn4AD8` (new) and `youtube:R0h33K7rw7Q` (changed) have body `e3b0c442...`, the SHA-256 of empty input. Both videos' captures became real in this release.

## Still open

- **`url_state` +21 is not proven row by row.** All 21 are on `intelligence.house.gov` hosts, have 0 attempts, and six pages there became real. The queue is built from links in page bodies, which are not retained here, and none of the 21 appear in `publisher_links`.
- **Recordings:** `Mv5g5Bn4AD8` ties to flips. `6xt7nTuO85A`, `Qfjzf5als_I`, `f1J38FlDKxo` and `senate:help031820` have no real capture and no publisher link or meeting video; their source is unknown.
- **Witnesses are sized, not fully classified.**
  - Of the 591 only-previous pairs, 535 are on `page:` occasions and 56 on `meeting:` occasions. Only 1 is a surname-matching respelling.
  - Removed names include non-people such as "download general", which looks like a correction.
  - Some meetings changed package: event 100039 moved from `CHRG-112hhrg72233` to `CHRG-112hhrg72232`, replacing its witnesses. Which is right was not checked.
  - The 758 extra occurrences include non-people, for example "prepared statement on h.r. _" going from 1 to 7.

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
