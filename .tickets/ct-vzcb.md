---
id: ct-vzcb
status: open
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

