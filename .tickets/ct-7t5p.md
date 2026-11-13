---
id: ct-7t5p
status: closed
deps: []
links: [ct-deg8, ct-wsu7]
created: 2026-11-08T13:44:49Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [docspec, datafusion]
---
# Land the DataFusion 55 type pins with the engine upgrade

Branch df55-types (backed up to GitHub at 30ba6655) holds the casts DataFusion 55 needs so published column types stay the same: capture_scheduler's NULL next_attempt_at branch named as Timestamp(us, UTC); url-state.sql requested_url and last_outcome cast to Utf8 (the 55.2 engine refused 122 offline-lane tests without them, apache/datafusion#27023); and source-annotations-final.sql's document_kind branch cast to List(Utf8), because DF55 keeps the filename table's element field id. Main still pins engine b0342a7 (DataFusion 53.1), so nothing is broken today. When the engine moves to 55: rebase (url-state.sql changed on main in bc0a146c), prove byte identity on b0342a7, run the offline lane on 55. The document_kind cast was saved from an uncommitted edit and has not been run on either engine. Related history: ct-wsu7, ct-deg8.


## Notes

**2026-11-10T03:26:46Z**

2026-11-10: the df55-types worktree was pruned (clean); branch df55-types (30ba6655, also on GitHub) still holds the casts. Branch r4-a (065f7fbd) is kept without a worktree: its one commit not on main, c6284e80 'Keep engine limits out of the semantic model profile (C3)', looks superseded by f33d957d (ct-oun5); confirm and delete the branch when the engine upgrade lands.

**2026-11-11T14:30:07Z**

validated 2026-11-11, left open: still not needed today. main pins b0342a7 (DataFusion 53.1) and the pin candidate is the one line (also DataFusion 53.1); branch df55-types is unchanged at 30ba6655 and was not rebased. Waits on a DataFusion 55 engine pin, which nobody has scheduled.

**2026-11-13T06:06:16Z**

2026-11-13 release acceptance complete. Main and the shared Mac runtime now select DocSpec 98a2d54077390a70703af0277a9ac2df9ce14cef (DataFusion 55.2): Darwin SHA-256 4c4a94c8638f7fcb7a0ca086e310cbe383df69518c24ab70143d1f6aa9512f28 and Linux ae75bb55e932d9ed156766499ef756e59a23498324cb59f54a7187b892657da9. The Linux binary was uploaded create-only to the private runtime bucket, read back byte-for-byte, and selected in DOCSPEC_RUNTIME_ARTIFACT. Main runtime doctor and scheduled disk admission passed.

All six native Linux production-offline shards passed: 13,433 tests, 31 subtests, 3 expected skips and 47 deselections. Five unchanged shards ran at 6cf02972; the full shard5 rerun at 4cba90b8 corrected one stale maintenance-table assertion and used the same original Linux binary. All 547 file assignments match the integrated source. Final Darwin qualification includes both original failed aggregate queries byte-identical to the DF53 predecessor, planted ordering-error detection, the full DocSpec gate and the full frozen production model.

The capture rebuild and remote readback preserve all 4,181,852 rows from 35,897 receipts except mapping_version. The guarded publisher released 55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105; all six required invariant suites (nine invariant/completeness reports in total) passed. Engine metadata changes were independently reviewed, the public manifest matched the sealed candidate, and browser/citation consumers passed. See docs/measurements/ct-7t5p-datafusion-55-20261113.md and .cache/archive-release/implementation/ct-release-20261112T2215/release/cutover/cutover-result.json.
