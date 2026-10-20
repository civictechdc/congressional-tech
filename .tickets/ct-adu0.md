---
id: ct-adu0
status: in_progress
deps: []
links: []
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Replace whole-corpus pickle staging with resumable typed preparation

Replace CatalogDependencyStorage.adopt whole-corpus SQLite payload staging with bounded typed partitions and reusable completed native work. Preserve source order, identity, aliases, duplicate/null/nested values and existing CatalogRows occurrence splitting. Reuse maintained storage and selection owners.

## Acceptance Criteria

Record before/after wall time, staging bytes and memory on identical fixture including large occurrences. Exact source/document/mapping equivalence. Interrupted continuation reuses completed work and refuses changed inputs. Detect capacity failure before expensive staging; preserve original failed operation.


## Notes

**2026-10-20T18:40:47Z**

Implemented typed Parquet dependency preparation with metadata-only SQLite indexes, fsynced hash-bound part receipts, fresh-process resume, source-row-group skip, checked file/schema/request coverage, aggregate staging budget, and bounded progress. No local native success authority: exact content-named CatalogRows writes replay through DocSpec. Selected v3 dependency and occurrence v1 formats remain readable/unchanged. Final focused suite80 passed/1 skipped/6 native-name deselected; earlier qualified native suite61 passed. Red9 failed/1 existing guard passed before implementation. Process loss os._exit(17), giant full source/document values+mapping equality, original hash partitions, sparse/global order, aliases/nulls/duplicates/unsigned/binary and changed-input refusal covered. Quiet identical1024row34.2MB fixture:2.109686s->2.221052s (+5.28%), peak temp29,978,624->2,373,710 bytes (-92.08%), peak processRSS562,642,944->405,323,776 bytes (-27.96%); both1459nativecalls/42424submittedrows. Evidence output/docspec-reuse-20261020/preparation. Await independent review and parent capacity integration; keep in_progress. No production/source-corpus writes, push, merge, archive or primary dirty edits.

**2026-10-20T18:47:14Z**

Scale review found repeated whole-part decoding in preliminary75091e05: at16,384rows with64-row leaves,995,200rows were decoded (60.7x). Current production leaf bound is8192rows. The preliminary disk-saving implementation is not approved; correct read amplification and measure rows/decoded bytes, peak memory and retained bytes before closure.

**2026-10-20T19:00:10Z**

Independent storage advisor supports sorted Parquet plus one sequential Arrow reader under the existing preparation receipt. Keep source_order as data and exact original Arrow schema; qualify null/empty/duplicate lists, unsigned maximum, binary, giant rows, spill, scratch refusal and restart. Existing native CLI offers lifecycle Run/Export, not stateless sort; bounded optional DuckDB dependency is justified only after those checks.
