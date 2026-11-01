---
id: ct-kac4
status: closed
deps: []
links: [ct-77zb, ct-h1nd, ct-d0o0, ct-sh4j]
created: 2026-11-01T17:43:18Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [refactoring, captures, sql, viewer-publication]
---
# Unify captures.py and capture_backfill_guard.py receipt-envelope parsing and extract inline SQL from archive_model.py

Eliminate split-brain receipt attempt/error extraction between captures.py and capture_backfill_guard.py, deduplicate House committee code normalization between Python and SQL, and move remaining inline SQL strings out of archive_model.py into model/sql/*.sql.

## Design

1. Factor shared receipt-envelope and nested-error extraction logic between packages/congress_api/src/congress_api/lake/captures.py and capture_backfill_guard.py (updating APPROVED_MAPPING in test_captures_version.py and publish-model.json if captures.py bytes change).
2. Keep normalize_house_committee_code in meeting_records.py as the single source of truth for hs* -> hl*/ht* normalization and simplify or share the SQL rule in model/sql/meeting-records-resolved.sql.
3. Extract remaining multi-line inline SQL steps (such as app_url_inputs_sql) from packages/viewer_publication/src/viewer_publication/archive_model.py into standalone files under model/sql/.

## Acceptance Criteria

- captures.py and capture_backfill_guard.py share one canonical receipt-attempt/error extraction path.
- All model SQL steps in archive_model.py load from model/sql/*.sql files with no multi-hundred-line inline SQL strings remaining.
- All offline regression and model tests pass.


## Notes

**2026-11-01T20:08:14Z**

Rejected 2026-11-01 after independent review. capture_backfill_guard.py has no envelope parsing to unify: it checks public rows and supplied per-receipt counts. The SQL rule matches 0 v21 rows, so delete it (ct-p3ff) rather than share it. The largest inline SQL string is 50 lines, so the extraction criterion is already met, and moving SQL changes file_hashes and input_digest, forcing a rebuild.
