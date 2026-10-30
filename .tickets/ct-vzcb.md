---
id: ct-vzcb
status: closed
deps: []
links: [ct-te1p]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, raw, b13, pdf, backfill, track4]
---
# T4.2 (B13): Adapt and run uncompressed .pdf streaming copier (pdf_backfill.py)

Per docs/plans/simplification-plan-20261024.md §6.2.13: replace the legacy accepted_files lookup in packages/congress_api/src/congress_api/retention/pdf_backfill.py with the BodyStore streaming copier over sniff = 'pdf' .gz candidates (~260,175 objects, ~403 GB), verifying SHA-256 and %%EOF and writing provenance/verification/ records.

## Acceptance Criteria

pdf_backfill.py uses BodyStore over sniff='pdf' candidates without accepted_files, verifies SHA-256 and %%EOF, and writes provenance/verification/ records across the backfill.


## Notes

**2026-10-30T15:21:37Z**

Committed at 7bab5c8d: replaced accepted_files / in-memory / ZIP / 512MiB cap / pre-upload HEAD in pdf_backfill.py and backfill_uncompressed_pdfs.py with BodyStore streaming copier (put_pdf_copy + select_pdf_candidates over sniff='pdf' .gz bodies), non-fatal SHA-256 mismatch recording, %%EOF + check_pdf intact check, 412 single-HEAD MD5 check, and provenance/verification/ JSONL records for both .gz and .pdf. 224 tests pass.
