---
id: ct-8bzh
status: open
deps: []
links: []
created: 2026-11-02T18:22:51Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [tests, flaky]
---
# house-naming audit acceptance tests time out under machine load (10 s subprocess limit)

2026-11-02 impl-model's full lane on r1b-model 1499dae7, run alongside model runs: two test_audit_acceptance cases hit their 10 s subprocess timeout; all 13 pass when re-run alone. A wall-clock limit in a test makes lane results depend on machine load, so a full lane run beside heavy jobs can report false failures.

## Acceptance Criteria

The tests bound work, not wall time (or use a generous limit that only catches hangs); they pass under a concurrent heavy job.

