---
id: ct-klql
status: open
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

