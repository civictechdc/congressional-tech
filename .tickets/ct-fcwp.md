---
id: ct-fcwp
status: open
deps: [ct-vnkf]
links: [cefr-9zd4]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, raw, b9, verification, track4]
---
# T4.4 (B9): Run initial raw verification listing baseline and schedule weekly maintenance verification

Per docs/plans/simplification-plan-20261024.md §6.2.9: run packages/congress_api/src/congress_api/retention/raw_verifier.py live to record the initial listing baseline in provenance/verification/ and schedule weekly runs via the maintenance job.

## Acceptance Criteria

Initial listing baseline is committed to provenance/verification/ and weekly verification runs are wired into the maintenance job.

