---
id: ct-6ysr
status: closed
deps: [ct-vzcb]
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, raw, b10, verification, track4]
---
# T4.3 (B10): Run one-time full re-hash of unverified older R2 bodies

Per docs/plans/simplification-plan-20261024.md §6.2.10: after B13, verify all remaining older bodies in R2 that do not yet have sha256_verified = true in provenance/verification/.

## Acceptance Criteria

Every retained body in R2 has a sha256_verified = true record in provenance/verification/.


## Notes

**2026-10-30T15:21:37Z**

Committed at 7bab5c8d: added full_rehash=True parameter to raw_verifier.verify() and --full-rehash CLI flag to congress_api.cli.raw_verify, selecting all non-missing bodies lacking a matching sha256_verified=True record and skipping bodies already verified by B13 or prior samples. Verified by test_raw_verifier.py (12 passed).
