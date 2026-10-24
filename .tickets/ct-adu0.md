---
id: ct-adu0
status: closed
deps: []
links: [ct-wjce, ct-dzlf]
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Replace whole-corpus pickle staging with resumable typed preparation

Replace `CatalogDependencyStorage.adopt` whole-corpus SQLite payload staging with bounded typed Parquet partitions, one bounded external sort (`ordered.parquet`) for ordinary hash-ordered leaves, and reusable completed native work. Preserve source order, identity, aliases, duplicate/null/nested values and existing `CatalogRows` occurrence splitting. Reuse maintained storage and selection owners.

## Acceptance Criteria

- Eliminate the preliminary `75091e05` $60.7\times$ random-part read amplification by ordering non-giant prepared parts once into `ordered.parquet` (`_order_sources` in `catalog_dependency_preparation.py:318-440`) and consuming ordinary hash-ordered leaves via a single sequential Arrow batch reader (`_peek`/`_consume`), while keeping oversized `giant=1` singleton occurrences outside the sorter.
- Enforce `staging_byte_budget` across both DuckDB sorter spill (`duckdb_temporary_files()`) and `ordered.parquet.tmp` output (`catalog_dependency_preparation.py:348-412`), and ensure `native_capacity.preparation_budget` (`ct-n7la`) accounts for the ordered derivative file.
- Record before/after wall time, decoded rows/bytes, staging bytes, sort spill peak, and process RSS on the identical fixture (including 16,384 rows with 64-row leaves and giant occurrences).
- Prove exact source/document/mapping equivalence, interrupted continuation reusing completed part/ordered receipts, refusal of changed inputs/schemas, and unsigned/binary/null/duplicate fidelity.
- Commit the working tree in `codex/docspec-typed-preparation` and integrate into `codex/docspec-reuse-integration`.

## Notes

**2026-10-20T18:40:47Z**

Implemented typed Parquet dependency preparation with metadata-only SQLite indexes, fsynced hash-bound part receipts, fresh-process resume, source-row-group skip, checked file/schema/request coverage, aggregate staging budget, and bounded progress. No local native success authority: exact content-named CatalogRows writes replay through DocSpec. Selected v3 dependency and occurrence v1 formats remain readable/unchanged. Final focused suite80 passed/1 skipped/6 native-name deselected; earlier qualified native suite61 passed. Red9 failed/1 existing guard passed before implementation. Process loss os._exit(17), giant full source/document values+mapping equality, original hash partitions, sparse/global order, aliases/nulls/duplicates/unsigned/binary and changed-input refusal covered. Quiet identical1024row34.2MB fixture:2.109686s->2.221052s (+5.28%), peak temp29,978,624->2,373,710 bytes (-92.08%), peak processRSS562,642,944->405,323,776 bytes (-27.96%); both1459nativecalls/42424submittedrows. Evidence output/docspec-reuse-20261020/preparation. Await independent review and parent capacity integration; keep in_progress. No production/source-corpus writes, push, merge, archive or primary dirty edits.

**2026-10-20T18:47:14Z**

Scale review found repeated whole-part decoding in preliminary75091e05: at16,384rows with64-row leaves,995,200rows were decoded (60.7x). Current production leaf bound is8192rows. The preliminary disk-saving implementation is not approved; correct read amplification and measure rows/decoded bytes, peak memory and retained bytes before closure.

**2026-10-20T19:00:10Z**

Independent storage advisor supports sorted Parquet plus one sequential Arrow reader under the existing preparation receipt. Keep source_order as data and exact original Arrow schema; qualify null/empty/duplicate lists, unsigned maximum, binary, giant rows, spill, scratch refusal and restart. Existing native CLI offers lifecycle Run/Export, not stateless sort; bounded optional DuckDB dependency is justified only after those checks.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit inspected the uncommitted fix in `/Users/mikewolfd/.codex/worktrees/docspec-typed-preparation/congressional-tech` (`catalog_dependency_preparation.py:262-270,308-507` and `tests/test_catalog_dependency_preparation.py`). Grade: B+. The external sort (`_order_sources`) + sequential window (`_peek`/`_consume`) and single-chunk struct indexing (`table['source_values'].chunk(0)`) directly fix the $60.7\times$ read amplification while preserving `giant=1` isolation, `source_order` data checks, and combined spill+output byte budgets. Remaining action: run the test suite and scale measurement in `docspec-typed-preparation`, verify `native_capacity.preparation_budget` covers `ordered.parquet`, commit, and cherry-pick into `docspec-reuse-integration`.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 88 → 88, work 74 → 78.
- Problem: Later regression from ct-2ukk (`48137619`): production-only branches on `PYTEST_CURRENT_TEST` (75 sites across 20 modules).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:22
- Covered by: WS1 (ct-dzlf), which removes the production-only `PYTEST_CURRENT_TEST` branches.
- See docs/reviews/2026-10-24-ticket-audit/README.md
