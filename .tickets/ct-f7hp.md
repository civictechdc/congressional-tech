---
id: ct-f7hp
status: in_progress
deps: []
links: [ct-vq2a, ct-94hw]
created: 2026-11-10T03:42:38Z
type: bug
priority: 1
assignee: mikewolfd
tags: [data-model, correctness, release-blocker]
---
# A newer identical copy renames a document and drops what its filename said

Release candidate at 8c3a3cae against live 630164505301: 621 documents take the filename, kind, family and facts of a byte-identical copy first fetched on 2026-11-08 at another address (democrats-edworkforce.house.gov, budget.house.gov), because model/sql/saved-files.sql leads the saved body with its newest-fetched source file. 576 of the names lose information (322 lose a House-convention name). The saved body, Congress, committee, meeting and date are unchanged (ct-vq2a took those from every copy). ct-94hw recorded the same behaviour as explained on 2026-11-04 (1,689 documents).

## Acceptance Criteria

A later capture of bytes the archive already holds never renames a document or changes its kind, family or facts; a recovery-only document later captured live at its original address still takes that address; the published address never goes blank; the saved body does not change. Measured effect against the live release recorded before any model run.


## Notes

**2026-11-10T04:40:00Z**

Rule (branch claude/ct-saved-name, 2c351724; not merged, not built). Among the saved body's named, addressed source files, one whose capture stored the bytes leads one whose captures only found the archive already holding them (`source_files.body_stored`: some capture row has outcome `stored`; `unchanged` is the other good outcome). Then saved-file order as before. The first window is untouched, so the saved body cannot change.

Why not "earliest fetch" or "richest name": measured on the candidate's own evidence (scripts and outputs in `.cache/archive-release/release-20261110/fixes/saved-name/`, `fs-*.py` and `fs-*.out`). The live release already shows the newest copy's name everywhere, so any rule keyed on fetch time or on the name renames far more than the 621:

| Second ordering | Of the 621, back at the live name | Other live documents renamed | Of those: gain / lose / neutral | Documents whose saved address moves against live |
|---|---:|---:|---|---:|
| As built (newest fetch) | 0 | 0 | | 630 |
| **Stored the bytes, then newest (this change)** | 620 | 1,442 | 1,363 / 60 / 19 | 1,689 |
| Earliest fetch | 345 (276 more take a House-convention name) | 31,950 | 22,522 / 5,562 / 3,866 | 125,748 |
| Convention name, then newest | 320 (276 more convention; 25 stay generic) | 21,373 | 21,373 / 0 / 0 | 21,679 |
| Convention name, reader fields, then earliest | 335 (276 more convention; 10 other) | 27,633 | 23,754 / 0 / 3,879 | 120,975 |

Gain and loss are the filename reader's own output (`source_filename_readings.valid`, then the number of fields it extracts). The last three rows are an owner decision: they rename 21,000 to 32,000 live documents.

Effect of this change against live 630164505301, simulated (the offline rebuild reproduces the candidate's saved body and filename on 351,274 of 351,274 original documents and `is_saved` on 577,660 of 577,660 address rows, `fs-02`, `fs-09`):

- The 621: 620 names return. 612 return in name, kind, family and facts. 8 more return by name and each holds a recovery record whose link filled live's kind or facts; the rebuild cannot see that fill. 1 (`E&L-SCIP Joint Hrg 06.28.22 - Testimony - GAO.pdf`) takes `6.28.22_sirois_testimony.pdf`, because live's own name came from a 2026-10-31 copy that stored nothing.
- The 198 recovery-only documents captured live: unchanged (one real file each).
- 1,697 other documents change their leading file. Every one is led today by a copy from the 2026-10-31 run (1,690) or the 2026-11-08 run (7) that stored nothing: the swap ct-94hw recorded, now reversed. 1,442 change name (1,359 take a House-convention name, 4 gain reader fields, 19 neutral, 60 lose reader fields: 19 `BILLS-117hr1833ih-Katko.pdf`-style names lose the bill type and sponsor and one fact, 41 lose only a trailing copy number). Kind changes on 1,381 (1,206 `testimony` to `witness-statement`, 77 filled, none emptied), family on 145, facts on 1,381 (1,359 more, 19 fewer). 11 gain a title from link text. 255 keep every value and move only the saved address.
- `sources.parquet`: 629 of the 630 `is_saved` rows return; 1,688 live-saved rows become unsaved and 1,689 unsaved rows become saved on those 1,689 documents. No address row is added or removed, and link keys and lookup keys are body- and address-derived, so they cannot move.

Limit of the rule: `body_stored` is the capture writer's flag. Every fetch before 2026-10-30 says `stored`, including 223,479 captures of bytes captured earlier (`fs-07`), so among those copies the newest still leads: 20,298 documents still show a plain name beside a House-convention copy of the same bytes (21,977 as built, `fs-13`). The rule holds for new captures only while the fetcher keeps recording held bytes as `unchanged`.

Tests: `test_a_later_capture_of_held_bytes_never_names_the_saved_body` (saved-files fixture) and `test_a_later_capture_of_held_bytes_never_renames_the_document` (end-to-end build) fail at 57f4f2fa and pass at 2c351724. The 25 test files that read saved files, source files or the model's plans, with the join audit and the repeat-cost lint: 370 passed, `production-offline (partial: 25 of 524 lane files; not a lane result): exit 0`. No full lane and no model build were run. No pin hashes this SQL; `docs/engine-first-data-model.md` §7.4 and §7.5 state the rule.

Open: build a candidate and confirm these counts on its diff against live; then the owner decides whether names should follow what the name says (row 5).
