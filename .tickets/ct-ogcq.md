---
id: ct-ogcq
status: closed
deps: []
links: [ct-f6xa]
created: 2026-11-24T23:04:25Z
type: task
priority: 3
assignee: mikewolfd
tags: [archive, warc, publication]
---
# Promote unwrapped WARC/ARC PDF and HTML payloads to primary archive blobs

Records whose saved_body is an application/warc+gzip or application/arc+gzip envelope currently publish as format='other' and saved_media_type='application/warc+gzip' (441 rows in docmeta_v7_3.parquet alone: ~301 PDFs and ~140 HTML pages, echoing the upstream envelope issue seen in ct-0hay). Keep immutable WARC/ARC envelopes in R2 for provenance and alternates, while promoting the unwrapped HTTP response PDF/HTML payload to its own CAS blob as primary saved_body/saved_media_type/format so site, MCP, and downstream tools get direct MIME types and inline rendering without per-consumer container unwrapping.

## Design

Compare envelope-level vs unwrapped-payload CAS keying, emit provenance alternates for the WARC/ARC envelope, and align with ct-0hay body_text selection.

## Acceptance Criteria

1) Unwrapped WARC/ARC PDF and HTML payloads are published with true format (pdf/html) and saved_media_type in detail.parquet; 2) Original WARC/ARC envelope remains preserved and traceable for provenance; 3) Release invariants and byte-hashed parser pins pass.


## Notes

**2026-11-25T04:02:49Z**

Completed & closed 2026-11-24: Audited 0e7084cd.../detail.parquet and capture_evidence.parquet: all 8,510 format='other' WARC/ARC rows (8,442 application/warc+gzip, 68 application/arc+gzip) were capture_index=1 external/provider-responses envelopes whose first 8 KiB held binary or non-UTF-8 payloads, causing sniff.py UTF-8 decoding to return 'other' before checking WARC/filedesc signatures. Every one (8,510 / 8,510) already has its unwrapped capture_index=0 sibling payload in R2 and captures at the same (receipt_key, receipt_line) and URL (7,661 already published in detail.parquet under true formats — 4,757 pdf, 2,902 html, 2 doc — making those 7,661 duplicates; 849 non-document listing/wrapper pages including 20 with recovered_document PDFs that promote to saved_kind='recovery'). Updated model/sql/record-roles.sql so c.format='other' with application/(warc|arc)(+gzip)? media_type classifies as record_role='envelope' (is_real_file=False), preserving immutable envelopes in R2 and 1:1 traceability in capture_evidence with zero byte-hashed parser or READING_VERSIONS drift (and zero live R2 backfill needed). Updated docs/engine-first-data-model.md and added tests in packages/viewer_publication/tests/test_phase1_model_roles.py and test_warc_payload_promotion.py. Verified 148 passed across 14 targeted production-offline files (including all 6 model invariant suites, test_archive_model_job.py, test_producer_identities.py, test_captures_version.py, .github/tests/test_definition_change.py), doctor, inventory (627 files), and tk dep cycle. Report: .cache/archive-release/investigations/ct-ogcq-warc-promotion-20261124.md.

**2026-11-25T12:01:56Z**

2026-11-25: Merged to main in PR #240 (6374ea1f, commit 5121659c, 12/12 CI green). Follow-up Gate-1 release-cause tracking split to a new ticket.
