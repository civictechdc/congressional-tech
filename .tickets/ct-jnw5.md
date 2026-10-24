---
id: ct-jnw5
status: closed
deps: []
links: [ct-2wsw]
created: 2026-10-22T18:42:15Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-4t6s
tags: [parquet, committee-explorer, docspec-views, docspec-rs, performance]
---
# Optimize Committee Explorer browser tables, eliminate docspec_views.py sources x witnesses Cartesian explosion, remove Snappy->ZSTD double write, and decouple row-group size from page index in docspec-rs

Physical metadata, raw-data, and code audit of Committee Explorer browser tables (parquet.py), docspec_views.py, docspec_client/docspec.py, and docspec-rs/src/engine/export/pipeline.rs revealed:
1. 100%-Duplicate, Constant, and All-Null Columns Across Browser Tables:
   - committees.parquet (699 KB): committee_ids (74.3 KB compressed, 10.63% of file) is 100.0% identical to [id] (3,432 / 3,432 rows); kind is 100% constant 'committee_term'.
   - meetings.parquet (3.97 MB): meeting_id (397.3 KB compressed / 764.0 KB uncompressed, 10.01% of file) is 100.0% identical to id (18,453 / 18,453 rows); explanation is 100.0% NULL; kind is 100% constant 'meeting'.
   - materials.parquet (44.76 MB): meeting_id (3.59 MB compressed) vs meeting_ids (3.64 MB compressed) — 99.69% of rows with a meeting (286,748 / 287,654) have meeting_ids == [meeting_id] (only 906 rows = 0.24% have >1 meeting); appearance_ids is 100.0% empty list []; files.saved_copy_sha256 and files.saved_filename are 100.0% NULL (not wired to R2); explanation is 99.997% NULL (only 11/377,989 rows populated); kind is 100% constant 'material'.
   - witnesses.parquet (8.17 MB): search_text (1.82 MB compressed / 5.26 MB uncompressed, 22.30% of file) is 100.0% equal to ' '.join([title, position, organization]) (parquet.py:334), where title, position, and organization are already columns in the same row; explanation is 100.0% NULL; kind is 100% constant 'appearance'.
   - issues.parquet (19.46 MB): issue_count is 0 for 100.0% (248,101 / 248,101) of rows; kind is 100% constant 'data_issue'.
2. Cartesian Product Fan-Out in docspec_views.py (extract_meeting_observations_from_stage, lines 284-332): Iterates 'for source in sources: for witness in witness_names:' per meeting, expanding 18,453 meetings into 62,975 rows (3.41x expansion, up to 82 rows for a single meeting d330169a-8581-4721-bb65-3a3cc71ee16c and 3.02x title byte duplication), then uses count_distinct and collect_set in downstream views just to undo the fan-out.
3. Snappy-then-ZSTD Double Write (parquet.py:85, 158 -> docspec_views.py:694): parquet.py sorts and writes all 8 Parquet files with Snappy compression, and export_browser_publication(..., replace_source_files=True) immediately reads them back into docspec-rs, re-sorts them, and overwrites them with ZSTD(3).
4. Row-Group vs. Page-Index Conflation in docspec-rs (pipeline.rs:797-805): When page_index_columns is set (e.g. ['id'] on sources), pipeline.rs sets write_batch_size(256) AND flushes a Row Group every 256 rows (creating 1,207 tiny row groups and 2.90 MB of footer overhead in sources-1..3.parquet). Page indexes prune at the 16 KiB data-page level inside a normal 16,384-65,536 row group.
5. UInt64 -> Decimal128(20, 0) Widening in docspec_client/docspec.py:786: native_storage_schema defaults to native_types=False, doubling UInt64 from 8B to 16B Decimal128(20, 0) and Binary to LargeBinary.

## Design

1. In parquet.py and apps/site/src/components/explorer/reader/, drop committees.committee_ids, meetings.meeting_id, materials.meeting_id (retaining meeting_ids), witnesses.search_text (searching title/position/organization directly), issues.issue_count, 100%-null explanation/appearance_ids columns, and constant kind columns (injecting kind from the table name on read), and wire materials.files.saved_copy_sha256 & saved_filename to R2 digests.
2. In docspec_views.py:extract_meeting_observations_from_stage, decouple meeting sources and meeting witnesses (or pre-aggregate per meeting) so explorer_meeting_observations has 1 row per (meeting, source) without multiplying by witness count.
3. Write browser Parquet tables in a single ZSTD(3) pass without writing temporary Snappy Parquet files first.
4. In /Users/mikewolfd/Work/spicy-stack/docspec-rs/src/engine/export/pipeline.rs:797-805, keep data_page_size_limit(16 * 1024) and write_batch_size(256) for page-index granularity, but set max_row_group_size to 16,384-65,536 rows instead of flushing a row group every 256 rows.
5. Default native_types=True in docspec_client/docspec.py:native_storage_schema.

## Acceptance Criteria

1. Redundant/all-null/constant columns removed across committees, meetings, materials, witnesses, and issues, and materials.files.saved_copy_sha256 populated for R2-backed files.
2. explorer_meeting_observations no longer multiplies sources x witnesses (max rows per meeting equals source count, not sources * witnesses).
3. Browser publication writes Parquet once in ZSTD(3), and page-indexed exports in docspec-rs use >=16,384-row row groups with 16 KiB data pages.
4. All committee_explorer, apps/site, and docspec_client tests pass.


## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 79 → 79, work 70 → 70.
- Problem: Meeting summaries now keep only the first witness, `saved_copy_sha256` is 0%, published tables lost their page indexes, and several tests check their own helpers.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:112
- Status: Closed as superseded by the simplification plan (WS11, ct-2wsw): explorer table work is frozen; its one-writer question goes with ct-gi01. Not covered: the witness roster regression (summaries keep one witness).
- See docs/reviews/2026-10-24-ticket-audit/README.md
