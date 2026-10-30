---
id: ct-6ysr
status: open
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

