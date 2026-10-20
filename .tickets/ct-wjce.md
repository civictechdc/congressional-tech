---
id: ct-wjce
status: closed
deps: [ct-adu0]
links: []
created: 2026-10-20T20:12:37Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Measure redundant occurrence copies during core sizing

`CatalogRows._occurrences` and `core_table` call `combine_chunks` on nested arrays while `fits_chunk` repeatedly computes core bytes. Source inspection indicates avoidable copying of already-single-chunk giant occurrence values; speed and allocation impact remain unmeasured. The `ct-adu0` preparation correction (`catalog_dependency_preparation.py:266-270`) reuses its own single arrays (`table['source_values'].chunk(0)`) but leaves this shared owner unchanged. Trace `packages/congress_api/src/congress_api/retention/catalog_rows.py:35-72` and retained preparation evidence. Do not reread the corpus, change production limits or alter occurrence semantics.

## Acceptance Criteria

- Use the retained synthetic giant fixture to measure buffer ownership, allocations or peak RSS, and wall time before/after across `fits_chunk` bisect splitting (`catalog_dependency_preparation.py:229-239`) and `CatalogRows` occurrence extraction.
- Reuse maintained single-chunk Arrow arrays (`chunk(0)` when `num_chunks == 1`) where safe in `packages/congress_api/src/congress_api/retention/catalog_rows.py:35-72`, preserving exact null/empty/duplicate values, order, and field metadata.
- Run focused `CatalogRows`/native round-trip checks and adopt the change only if measured allocations, peak RSS, or wall time improve; make no speed claim without measured evidence.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit promoted `ct-wjce` from the untracked file in `docspec-typed-preparation` into the central `ct-mi03` ticket set and linked it to `ct-adu0` and `ct-nc7l`.
