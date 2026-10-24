---
id: ct-7uit
status: open
deps: [ct-q2ht, ct-qqk2, ct-70kc]
links: [ct-13cn, ct-gziq, ct-bwac, ct-nc7l, ct-sb0s, ct-czsd, ct-2ukk, ct-si9g, ct-v5kb, ct-upte, ct-7e7q, ct-rcs8, ct-5kb2, ct-9vtu, ct-y32m, ct-l5q1, ct-gd8v, ct-dat9, ct-qdkd, ct-13g5]
created: 2026-10-24T18:15:54Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# Move incremental catalog updates onto the engine and delete the Python incremental layer

WS7 under decision 6 (engine first). congressional-tech keeps no incremental machinery of its own: the catalog is the engine's job, and the application supplies specs (keys, SQL, merge rules, the `document_id` expression) and calls engine operations. 22 Python incremental modules and the `catalog/` facade (9,248 lines, plus 35 test files, 6,744 lines) go whatever Step 0 finds.

First move: delete the manufactured consumers - the scratch-scope dataset blocks (`catalog_dependency_storage.py:684-826`, `source_observations.py:700-760`), `last_change_report` and `last_refresh_summary`, the streaming change count (`native_capacity.py:281-316`) and their self-referential assertions (`test_native_features.py:913-994`). Tests on `prepare()`'s result stay green.

Then:
1. Map each step that turns captures and state into the filename and document tables onto an engine operation: keyed `UpdateMergeSpec` merges with key pruning, `CollectSet` and list/struct aggregates, `ConnectedComponents` for document grouping, partition specs. Write the map as a table in the PR. A step with no engine operation becomes a generic docspec-rs ticket under ss-oxg1, never congressional-tech code.
2. Prototype the documents table on real data: an engine-native incremental update from the current selection with one day's change set, compared with the Step 0 rebuild using the harness's `--compare-only`, recording time, memory and objects read and written.
3. Promote the rebuild as the oracle and recovery tool: move the oracle and lineage files (403 lines) into a production module behind an explicit `rebuild` operation that reads captures and state from the native raw selection.
4. Delete the Python incremental layer, the adopt/qualify-sources/upgrade-source-rules modes and the native branches named in the plan; `native_features.py` shrinks to thin engine calls.

Keep `partition_routing.py`, the raw-side routing pages and the oracle's own modules, re-checking each against decision 6 as it is touched. The DuckDB external sort, typed-preparation resume, the spill arena (ct-4g55) and the reuse cache (ct-3bfx) stay only if the rebuild's profile needs them; if the engine prototype needs them, they belong in the engine.

## Acceptance Criteria

- Step 0's comparison C finds no class (iii) difference before anything is deleted.
- The differential test (`test_catalog_raw_updates.py:63-86`) is retargeted to compare engine-native incremental output with the rebuild.
- A raw-to-catalog invariant test: every retained capture yields its source row, and `source_id`/`document_id` are identical across two rebuilds.
- A frozen ID fixture for a PDF row, and the shared `document_id` golden vector (docspec-rs WS9 step 8).
- The derivation-to-engine map is committed; every gap has a linked ss-* ticket.
- The documents-table prototype matches the rebuild and beats Step 0's baseline by a clear margin; otherwise the daily update is the rebuild.
- R-check 1-3 pass; derived writes go through WS2's policy.

## Notes

**2026-10-24T18:21:03Z**

File each missing engine primitive under the docspec-rs epic ss-oxg1 (spicy-stack) and link it here. The shared document_id golden vector comes from ss-jv5t.
