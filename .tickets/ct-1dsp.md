---
id: ct-1dsp
status: closed
deps: []
links: [ct-fw0m, ct-jl1m, ct-rrfm, ct-m59w]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Remove duplicate viewer inventory hashing

The prepared viewer inventory is rehashed within preparation and again in verification/publication entry points. Several passes validate the same bytes under unchanged local custody.

Trace: scripts/viewer_publication_attempt.py prepare/verify_prepared/publish, Continuation.phase, and publish-viewer-r2.py prepared_files.

## Acceptance Criteria

Document and test the full-file hash budget per custody boundary. Reuse only process-local proof tied to exact files, code, and inputs; keep a full integrity check after artifact restore. Changed files or forged/stale proof must fail before publication.

<!-- grade-followup:start -->
## Grade review follow-up

Account for index_recoveries filename/group hash checks when counting same-process prepared-file integrity passes.

- A proof used by recovery indexing binds exact local files, selected inputs and validator identity; changes invalidate it before use.
- Artifact restoration and fresh custody retain full integrity verification; no global trust cache or unverified skip flag.

prepared_files, verify_prepared, Continuation.phase and upload.transfer local-byte verification.

- Separate structure from exact inventory proof; retain all ID-shard hashes, size/path checks and independent restore verification. Instrument hash bytes and passes, including downstream transfer hashing; proof cannot be forged through JSON or survive changed custody.

[Function scope and checks: 8 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:194). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:27:13Z**

Implemented issued process/file/input/validator-bound inventory across builder→phase→verify→recovery→guarded upload/replay. Fresh artifact verification hashes each inventory file once including256 ID shards, then structural/phase/transfer handoffs reuse exact proof; dict/copied/inherited-process proofs refuse. Guard pins hash once per unchanged process custody while cloud/protected checks stay fresh. Fresh phase count/path refusal preserves previous checkpoint. 116 tests+2subtests; final40 proof/process/provenance tests pass. Hash budget and custody assumption recorded in preparation-inventory.md.
