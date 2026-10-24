---
id: ct-f11a
status: closed
deps: [ct-jo8n]
links: [ct-jo8n, ct-4nyy]
created: 2026-10-20T23:52:13Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, export, efficiency]
---
# Export C5-filtered news releases without synthetic release UUIDs or triple Parquet writes

DocSpecNewsViews.export_authorized (packages/news_lake/src/news_lake/storage/docspec_backend.py:1478-1591) has two architectural defects identified in the CS 300 audit of ct-4nyy: (1) _ensure_release_read (:1488-1505) fabricates a synthetic release record with dummy UUIDs (00000000-0000-5000-8000-000000000000 and 00000000-0000-5000-8000-000000000001) when passed raw records instead of requiring an authentic published release pin; and (2) for every table (:1530-1575), it writes Parquet three times: staging source.parquet into a throwaway export_{logical_dataset} via run_table (:1538), materializing export.parquet via client.export (:1564), and copying it again via shutil.copyfile (:1575)—even for tables that have zero C5 row/field redactions and already have an exact pinned dataset version.

## Acceptance Criteria

- Require an authentic release structure in export_authorized (removing dummy UUID fabrication in _ensure_release_read at docspec_backend.py:1488-1505) and wire a non-test export caller in packages/news_lake.
- For tables unchanged by C5 filtering (or authorized exports where rows equal the pinned release dataset), run native ExportSpec directly against the release's pinned dataset VersionRef instead of re-admitting a duplicate export_{logical_dataset} via run_table.
- Avoid redundant file copies when reading or verifying exported Parquet output, and test old-export pin readback after a newer channel export is selected.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to address the CS 300 C+ deduction on ct-4nyy: remove dummy UUID fabrication in _ensure_release_read (docspec_backend.py:1488-1505) and eliminate triple Parquet writes (run_table -> export -> shutil.copyfile at :1530-1575).

**2026-10-21T00:31:34Z**

Implemented in DocSpecNewsViews.export_authorized: _ensure_release_read now refuses raw record lists instead of fabricating release UUIDs; optional dataset_pins lets an unchanged C5-filtered table export the exact release pin without re-admitting a staging dataset; delivered files use a hard link with copy fallback and streaming digests. Added tests for strict release identity and direct pinned export. news_lake backend tests: 12 passed.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03a).
- Grades: proposal 88 → 85, work 84 → 84.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
