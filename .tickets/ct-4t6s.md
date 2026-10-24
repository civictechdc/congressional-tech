---
id: ct-4t6s
status: closed
deps: [ct-8v02, ct-xx7q, ct-q29c, ct-v9ua, ct-8od2, ct-jnw5]
links: [ct-syx8]
created: 2026-10-22T18:40:32Z
type: epic
priority: 0
assignee: mikewolfd
tags: [parquet, r2, docspec, schema, normalization, deduplication]
---
# Parquet & Raw Data Audit: Direct-to-R2 payload offloading, full columnar normalization, row/column deduplication, and physical layout optimization across all docspec-rs output tables

Comprehensive remediation of all findings from the Parquet & Raw Data Audit (parquet-output-tables-audit.md) across all 6 output domains of congressional-tech -> docspec-rs (Committee Explorer Browser Publication, Explorer DocSpec Views, Weekly Retention Tables, Raw Capture Archive, Canonical Catalog & Dependency Graph, and Viewer Publication / News Lake). Centers on moving raw JSON/HTML/XML/PDF payloads directly to R2 content-addressed storage (/bodies/sha256/<xx>/<sha256>.{gz,pdf}) while normalizing all structured fields into typed Parquet columns, fixing 5 broken weekly_tables row builders, eliminating 94,974 duplicate/orphan source rows, dropping 100%-redundant columns (body_key, 47 source_* cols, meeting_id, committee_ids, witnesses.search_text, record_json), and fixing Parquet row-group/footer bloat.

## Acceptance Criteria

1. Zero raw JSON/XML/HTML/PDF blobs embedded in browser sources.parquet, weekly_tables, or review/rows; all raw bodies stored in R2 (/bodies/sha256/<xx>/<sha256>.{gz,pdf}) and linked via SHA-256 digests with all structured fields normalized into typed Parquet columns.
2. All 5 broken row builders in weekly_tables.py fixed and verified against real pipeline-data inputs with non-null key/merge assertions.
3. All 74,759 duplicate (provider, identifier) rows and 20,215 unreferenced orphan rows eliminated from sources.parquet.
4. Redundant body_key, stored_sha256, 47 duplicate top-level source_* columns, and 100%-duplicate/all-null browser & viewer columns removed or derived on read.
5. Parquet row-group sizing decoupled from page-index data-page sizing, cutting filenames/documents/sources footer overhead by >90% and compacting readings/*.parquet.


## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 80 → 80, work 60 → 60.
- Problem: The five numeric ACs (>90% footer cut, ~184 MB, ~350 MB, -94,974 rows) have no committed measurement.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:109
- Status: Closed as superseded by the simplification plan (WS2 ct-syx8, WS10 ct-r6xw, WS11 ct-2wsw): no child is reopened. WS2 step 9 makes the hand-written body writers call `put_body`, the plain fix this epic missed; WS10 deletes the weekly mirror and ct-8od2's helpers; explorer layout work is frozen. The `stored_sha256` overwrite was fixed in `54a68ac7`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
