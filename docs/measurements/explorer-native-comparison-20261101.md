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
