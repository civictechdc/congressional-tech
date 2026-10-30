---
id: ct-klql
status: closed
deps: []
links: [ct-v967]
created: 2026-10-24T18:46:38Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-syx8
tags: [audit-20261024, efficiency]
---
# Verify each raw upload once

Efficiency pass E4/E12. Recovery import does two GETs per body (presence plus readback), up to six SHA-256 and two MD5 passes, and decompresses its own output (transfer.py:107-136, checked_put :26-46, r2.py:112,128). R2 already verifies Content-MD5 on a create-only PUT, so a successful write needs no readback. Plan section 7, E4.

## Acceptance Criteria

- Raw and recovery uploads are create-only PUTs with Content-MD5 and Metadata sha256.
- A HEAD comparing the sha256 metadata and length runs only after a 412 or a lost acknowledgment; no full GET on the success path.
- Each byte stream is hashed once per algorithm; digests from body_payload are reused.
- Tests that pin two reads per key (test_import_corpus_recovery_batch.py:106,194-208) are rewritten deliberately, plus a test that a forged or mismatched existing object is refused.
- R-check 1-3 pass.


## Notes

**2026-10-30T16:49:25Z**

Verified completed in docs/plans/simplification-plan-20261024.md §6.2.3-6.2.5 (B3-B5, cefr-81oe commit 9a3674cd, cef-s4vp, cef-u7wj) and F5 G12 (commit 8978b3bb): BodyStore performs create-only PUTs with Content-MD5 and sha256 metadata without full GET readback, and legacy corpus_recovery/transfer.py checked_put was deleted in commit 8978b3bb. Verified by uv run pytest -q packages/congress_api/tests/test_body_store_contract.py.
