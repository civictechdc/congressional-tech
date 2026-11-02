# Explorer to native comparison, 2026-11-01

Frozen-input numbers. They may move: v21 captures disagree with current captures in at least 12,873 rows, and the archive-member eligibility rule (`ct-qg8e`) is undecided. The ledger is in `explorer-native-comparison-20261101.json`.

## Inputs

- Old release `56c87f8a7e29314d9e1477c0` from pipeline-data.
- Documents, meetings and witnesses from live release `448651e7`, each checked against its manifest sha256.
- The five new tables and the resolved meetings, built by `scripts/measure/explorer_tables_frozen.py` from v21 frozen inputs.
- `video_records` and `committee_records`, produced locally from public bodies.

This is not a full model run. It does not prove byte identity of other files, the real `detail` size, the release ID or full-job memory.

## Commands

```
python scripts/measure/explorer_tables_frozen.py --spec SPEC --release V21 --lake LAKE --decisions DECISIONS --output TABLES --runtime RUNTIME
python scripts/measure/explorer_native_comparison.py --old OLD --release V21 --overlay TABLES --data apps/committee_youtube/data --lake LAKE --decisions DECISIONS --output RESULT.json --release-id ID --commit SHA
```

Both run through the guard. The builder took 1.5 s and 873 MB RSS at a 1 GiB pool. The comparison took 2.3 s and 749 MB.

## Results

| Family | Old rows | Matched | Old only |
|---|---|---|---|
| Meetings | 18,453 | 18,141 | 312 other-source meetings |
| Document files | 335,973 | 325,590 | 10,383 pending print links |
| House documents | 18,126 | 17,993 | 133 |
| Senate documents | 14,606 | 11,172 | 3,434 pending page links |
| Amendments | 19,985 | 19,984 | 1, where the CSV text is double-encoded and the native value is correct |
| Curated decisions | 7,200 | 7,200 | 0 |
| Recording pairs | 16,313 | 8,100 | 8,213 pending matcher |
| Completeness | 17,606 | 17,606 | 0 |
| Videos | 67,351 | 67,351 | 0; 22 new from the later snapshot |
| Channels | 119 | 119 | 0 |

All 264,732 old issue rows, in 35 title and status classes, have a disposition. They stay by old-release reference.

Value checks found 0 mismatches: 200 curated verdicts, 200 meeting dates, 200 video titles and 119 channel IDs.

## Full value comparison

`scripts/measure/explorer_full_compare.py` reads every row on both sides and walks raw XML and JSON without the repository's parsers. Results are in `explorer-full-compare-20261101.json`. A script restating a rule, such as the merge order, cannot catch a shared misunderstanding of that rule.

| Check | Records read | Values read | Differ |
|---|---|---|---|
| Resolved meetings against raw Congress.gov and House records | 18,140, from 24,430 of 24,430 raw records | 217,794 | 0 |
| Meetings against v21, ten columns the old SQL wrote | 18,687 | 186,870 | 0 |
| Videos against raw cache JSON, 11 columns | 67,373, from 52 of 52 bodies | 741,103 | 0 |
| Channels against the CSV and raw JSON | 119 | 952 | 0 |
| Committee records against raw XML, eight columns as whole rows | 19,985 | 19,985 rows | 0 |
| Committee records against the old CSV, nine columns as whole rows | 19,985 | 19,985 rows | 1, the garbled CSV row |
| Curated decisions against the CSVs | 7,200 | 28,796 | 0 |

**Not read in full:** publisher-link and video-claim rows of `recording_matches`, and `meeting_coverage` against raw. Coverage is compared with the old file by column in the ledger. Early runs of this check found errors in the check and the builder, not the model: an unordered row position, and whitespace.

`committee_records` reads only `meeting-documents/meeting-document`, and this check walked grouped documents too and found no missing row.

Reparsing all 24,430 raw meeting records under the new pins found end times 532 of 532, rooms filled 146, buildings filled 107, and field addresses 109, none lost.

Old witness rows (`ct-x78c`), distinct by event and normalized name: 19,475. On the event 11,779; held on a package occasion without an event link 924; on a page occasion without one 5,472; event has other witnesses 451; no native row 849. The 6,396 occasion rows need the event link; the 849 have no migration yet.

Top-level rows with no recorded completeness: all 242,293 raw entries read. An earlier version of this note was wrong: it checked `url` only. 241,910 are digest-verified retained files with no response. 383 state HTTP 200 and a `context_url`. 73,308 have no other good row; of those, 73,307 have no address and no status, and one states HTTP 200 with a `context_url`: `CHRG-119hhrg64404`'s transcript HTML, body `5e9b5643...`. That one is wrongly excluded by the completeness rule, which is left unchanged and needs an owner decision. Whether retained files with no address should list is also an owner question.

## Imported ZIPs (`ct-64el`, owner decision)

15 Senate Finance ZIPs were fetched directly but expanded only by a retained import. Read from raw: 15 of 15 lines state HTTP 200, complete and completed processing; 15 of 15 ZIP bodies rehash to their digest, and each has a good download with that digest. 149 of 149 members state completed and rehash correctly. The model now counts them through `good-archive-containers.sql`; a fixture of this raw shape covers the member, ZIP link key and URL lookup, and an import with no matching download stays out. This changes `filename-inputs.sql`, so `catalog_version` moves and needs recomputing at integration.

## API responses are not documents (`ct-n2cy`)

All 345 JSON rows in `list` read in full: 324 are provider envelopes whose wrapped bodies all have their own rows, 12 are YouTube `videoListResponse` pages, and 9 are Wayback lookups. `record-roles.sql` now gives all JSON the `api` role. The 12 pages name 574 videos; 571 are in `videos`. `OxCoikJbuMw`, `hCg0yJjUJEA` and `xYlb_m1rNnY` are not in the latest caches, and this reading did not establish why.

Trace: the role admitted JSON as a document unless its URL matched an API pattern, so a response with no URL passed; a document with no filename or address was never checked, and `sources.url` was not declared required. The role layer owns the fix.

## Access and rescheduling, decided from raw

`closed`, 140 differences, all raw titles read: old rule wrong on 74 (including 48 briefings and 8 depositions with no closed session stated); 64 state a separate closed session, now `partly_closed`; 2 name a closed event, now `closed`. After the fix: 660 agree as `closed`, 85 are `partly_closed`, and the 74 stay `open` or `unknown`.

Rescheduled, after using publisher status and no longer counting transcripts: 12 same event, 32 old only, 8 new only, 17,554 neither. 11 rest on publisher status and 35 on a recording on the later twin. The old-only rows need the native matcher's evidence, and the new-only rows are unread per row. `not_held`: 2 old-only rows come from page titles.

## Coverage against independent evidence

`explorer_class_validation.py` reads raw records and old inputs per class: 24,430 of 24,430 meeting records, and 774 caption track bodies. Cross-tabs are in `explorer-class-validation-20261101.json`. They show where the rule is weak, and these are not fixed:

- **Documents:** 1,450 `not_stated` meetings have documents in raw or old files, because `list.meeting_keys` doesn't link them.
- **Transcripts:** 785 `not_stated` have an old GPO package, and 640 `present` rest on publisher jackets alone, which the old matcher distrusts.
- **Witnesses:** 1,906 `not_stated` have old rows, mostly the page and package occasions below.
- **Captions:** 1,377 `unknown` and 553 `not_stated` have old YouTube captions, pending links from the matcher. One track body is empty.
- **Recordings:** 4,477 `unknown` and 1,995 `claimed` have old `yes`, pending the matcher.

## Old witness rows with no home (`ct-x78c`)

1,300 distinct rows, 849 on events with no native witness. Not migrated; family-name matches are leads. docs.house.gov 976, of which 98 have the surname in raw House meeting XML: proposed ticket below. Senate pages 269: `ct-x78c`. Meeting titles 50 and witness list PDFs 3: no native parser, proposed ticket. GPO 2: `ct-x78c`.

## Proposed ticket text

- **`ct-deg8`:** a computed `THEN` branch in `CASE` inside `named_struct` in an ordered `array_agg` exceeds the memory pool (14.6-20.4 GiB at 1 GiB on 3,000 rows). A regexp is not required; literal branches, no `ORDER BY`, and pre-projecting all stay small. Pool settings do not bound RSS. Reproduction: `scripts/measure/engine_gap_ordered_array_agg.py`.
- **`ct-n2cy`:** classify API responses and envelopes as non-documents in `record-roles.sql`; 0 NULL `sources.url`, refused at write time. Started when the JSON role depended on a URL pattern, and nothing checked a document with no name.
- **New:** House witnesses missing from native appearances, and whether meeting-title nominees and witness list PDFs need a parser.

## Raw record readings

Raw means the stored body or receipt line. Derived tables only named which records to read. `scripts/measure/raw_meeting_audit.py` and `raw_findings_audit.py` hold the method; results are in `explorer-raw-sittings-20261101.json` and `explorer-raw-findings-20261101.json`.

| Finding | Read of affected | Result |
|---|---|---|
| 6,157 changed sittings | 6,165 of 6,165 Congress.gov and 6,179 of 6,179 House records | Every published start, room and building equals raw Congress.gov. All 6,179 House times are unzoned and, read as Eastern, equal Congress.gov. House states `meeting-location/capitol-complex` on 6,037 records and never the tag the parser reads. |
| 1 garbled amendment | 1 of 1 | The raw XML holds correct UTF-8, so the CSV is what is garbled. |
| 45 absence conflicts | 55 of 55 meeting records, 53 of 53 videos | Publisher records name none of the videos. 43 have a disputed negative verdict, now `unresolved`. In 2, a sibling package has a date-and-title match and no verdict; absence now needs every package to be negative. |
| 2,138 stronger-method pairs | 572 of 572 meeting records, 2,137 of 2,138 videos | 1,469: the GPO row has no event ID. 601: the event in raw differs, which suggests a same-day meeting link. 61: the package has no meeting link. 6: raw supports the claim but the native pair is missing, and in all 6 the transcript link names a different event. 1: video `P3YYBcmNckM` is not in the raw cache. |
| 6,955 witness rows | see below | Classified by source below. |

The excess over the plan is not new rows. 8,213 pairs are 6,075 date-and-title only plus 2,138 with a stronger method. The plan's 6,108 counted packages' pairs by a different cut, and its derivation is not reproducible here.

| Witness rows | Rows | Read | Result | Owner |
|---|---|---|---|---|
| Senate committee page | 4,814 | 4,696 | Family name in the raw page on all read; 118 rows have no held page | `ct-gi01` R2 derived-link layer |
| GPO | 926 | 926, across 247 of 247 MODS | Family name in raw MODS on all; 245 packages have native package occasions | `ct-gi01` R2 hearing records |
| House XML (counted in both CSVs, 586 each) | 579 distinct | 579, across 1,924 bodies | Family name in raw XML on 390, absent on 189 | Proposed new ticket below |
| Meeting title or witness list PDF | 43 | 0 | Sources named but not read; no native parser reads them | Proposed new ticket below |

Family-name presence is a lead for identity: it shows the raw text has the surname, not that the record lists that person as a witness.

Proposed ticket: "House witnesses missing from native appearances. For 137 events, retained CSVs list witnesses from docs.house.gov but `appearance_records` has no `house_xml` row. Read the House witness XML for those events, and decide whether meeting-title nominees and witness list PDFs need a parser."

## Root causes

| Bug | Cause and origin | Recurs in | Owning layer | Why it missed |
|---|---|---|---|---|
| House sittings 4-5 h early | Parser emits unzoned local text; annex declares `timestamptz`; SQL cast it as UTC (`ab543cef`) | `updated` for House ranking in `meeting-records-current.sql`; the same literal in `appearance-records-resolved.sql` | Parser should state the zone. Proposal only: byte-hashed. SQL conversion stands until then. | Fixtures use `Z` times, so no test held an unzoned value. |
| Lost House locations | Parser reads `capitol-complex-location`, a tag absent from all 6,179 records (`9e656389`) | `test_phase2_meeting_appearance_lake.py` fixture encodes the wrong tag | Parser. Proposal only: byte-hashed. Congress.gov-first is a workaround until then. | The fixture was written to match the code rather than a real body. |
| False `confirmed_absent` | My coverage rule read one package, not the meeting (`1e1fdbd5`) | Any meeting with several packages | Coverage SQL, fixed. Disputes live in the provenance import until the matcher replaces them. | My fixtures had one package per meeting; the comparison caught it. |
| Pair excess | Plan estimate cut pairs by a method not recorded | Other plan estimates | Native hearing records in R2 | The plan measured against derived CSVs only. |
| `meetings_resolved` memory | Engine gap on ordered `array_agg`; statement inlined CTEs per reader (`ab543cef`) | Multi-reader CTEs listed in the commit; `appearance-records-resolved`, `entity-bills`, `entity-recordings`, `url-keys` unmeasured | Engine for the gap, filed. SQL pre-projection is a workaround. Steps are the right fix for repetition. | Run at a 34 GiB pool, and nothing gates repeated evaluation. |
| `body_admissions`, `placeholders` memory | `GROUP BY` over all captures (`23f7d5ea`, `cd05dfdb`) | `c.*` chain from `capture_evidence` through `capture_source_names` and `capture_sources`, unfixed | Model SQL, fixed. Should also be an offline plan gate. | The rule reached `AGENTS.md` only in `d702d7bf`, and no gate enforces it. |

## Depends on `list_row` or document grouping

Rerun these after a rebuild: meeting transcripts, documents coverage, recording pairs and document-file accounting.

## What this cannot see

The ledger proves completeness, not that each reason is right. Natural keys can hide a wrong value, and name normalization can merge two different people.

## Round 1b meeting rules (2026-11-02, branch r1b-f)

Inputs: v21 frozen inputs, cluster C's frozen lake, all 24,430 meeting records reparsed under the new
`meeting_records` code (read 24,430, unread 0, failed 0; 2.45 GB RSS). Before = the base SQL with
cluster C's reparse; after = this branch. Both built by `explorer_tables_frozen.py` with an empty
`url_variants`, so Senate page keys may differ from v21, equally on both sides. Per-row raw reads are in
`meeting-semantics-raw-check-20261102.json` (`scripts/measure/meeting_semantics_raw_check.py`, which reads raw
without `meeting_facts` or the model SQL).

| Change | Plan estimate | Frozen measured | Raw read per row |
|---|---|---|---|
| access closed → partly_closed | 7 | 7 | 7 supported |
| not_held | +407 / −5 | +404 / −5 (3 status conflicts held) | 409 supported |
| status where both sources state one | 0 | 0 | — |
| rescheduled_to | 46 → 83 | 46 → 77 after own-evidence and type rules | all 77 links and 8 removals judged from the raw record's own transcript file, witnesses, video and type, not the rule: 78 supported, 0 contradicted, 7 ambiguous (reworded twin titles, read as the same hearing). Before the fix the same check contradicted 6 links: 116450 (own transcript, 14 witnesses, twin a markup), 110230 and 110947 (own witnesses); 114353, 116505 and 118044 are Postponed with later uploads, not contradictions |
| House witness lists attached by links or receipt path | 227 records | 227 (captures augmented with receipt `original_path`) | 187 body links = path; 40 path only |
| package witness rows changed | 392 rows on 93 events | 1,580 record×occasion changes | 133 supported, 1,416 ambiguous (no MODS eventId; raw cannot choose), 31 unread (MODS absent from the refresh) |
| documents unknown (Senate) / unresolved | 2,051 / 7 | 2,051 / 45 | premise only; 38 of the 45 link once `ordered` is rebuilt |
| witnesses unknown | Senate 3,188; House ~470+ | Senate 2,871; unattached 590 | premise only |
| transcript | 122 unknown | 129 present via MODS links, 14 unknown | 10 unread |
| captions not_stated → unknown | 7,853 | 7,837 | premise only |

No raw record can prove `unknown`; for coverage relabels only the premise is checked. Document links
(estimate 2,089 new pairs on 458 events, 38 events gaining their first document, recounted in DuckDB from the
reparse) need `ordered` rebuilt and are confirmed only by a full model run. Witness keys: 3,921 rows gone and
3,253 new (occasion changes), for ct-qg8e.

ct-x78c ledger (distinct old rows 19,475): `on_event` 11,779 → 12,856; House lists unlinked 579 → 110 (the
remaining House rows include the 40 lists that state their event only in a receipt path, which attach once
captures carries `original_path`); package occasions 924 → 660.

Coverage relabels by aspect are in `by_aspect`. The 333 recording changes: 331 hold their premise in raw MODS;
103474 (present → claimed: the video verdict was on CHRG-114hhrg94654, a different hearing; only the MODS-named
CHRG-114hhrg94653 counts) and 108050 (unknown → partial: the MODS-named CHRG-115hhrg33807 has excerpts) are read
and correct. The 3 witness `premise_fails` (108680, 108742, 118439) are markups whose MODS-named print has no
witnesses; a same-day sibling print with no eventId (another hearing, by title) holds witnesses, so the label
`package_witnesses_unattached` is conservative there.

### Re-review (red-f, 2026-11-02): prints checked by date and title

The raw check was rebuilt to judge from independent facts: MODS held dates, titles and eventIds read with
ElementTree from all 35,020 MODS bodies in the mirror (45 packages have no MODS record and stay unread);
Congress.gov lines; video publish days. Titles compare by token containment of the print title in the
meeting title (or difflib ratio), not the model's shared-word rule. The frozen after-build adds the
appearance_records mods `held_dates`/`title` re-derived from those bodies (witnesses unchanged: 0 drift).

| Family | Rows | Raw verdicts |
|---|---|---|
| not_held | 430 | 428 supported; 116426 and 116998 differ only because the check reads publish days, the registry live-stream times |
| rescheduled_to (78 links + removals) | 85 | 83 supported, 2 ambiguous reworded titles |
| print attachments changed | 536 | 448 supported, 83 ambiguous, 5 contradicted: generic Senate prints ("Pending Legislation", "A Review of the SBIR-STTR Program") the model leaves package-only, and 105231, a hearing print the check pairs with a same-day markup |
| House witness lists | 227 | 187 body links, 40 receipt path only |
| coverage relabels | 14,555 | premise holds 6,192, ambiguous 71, fails 9 (3 recording: HASC compilation volumes and a long print title the check under-scores; 6 witnesses: the generic prints above), unread 38 |

Red-f's cases: 330128, 329130, 335820 now carry their own prints (CHRG-117shrg50802 "Cryptocurrencies",
53087, 59430), CHRG-117shrg52109 and CHRG-116shrg37808 are package-only, 326063 says witnesses unknown,
101498, 101400, 104460 and 101644 are held (status Canceled kept), 101422 still moves to 101545, 116450
does not move, and Haaland 328803 carries its two-day print. not_held 409; rescheduled_to 78. Witness rows
147,888 -> 139,077: about 10k MODS rows now sit on meetings whose House XML or Congress.gov list outranks them.
