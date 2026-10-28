---
id: crnb-egqc
status: closed
deps: []
links: []
created: 2026-10-28T14:17:16Z
type: task
priority: 0
assignee: mikewolfd
---
# Bound native CI test clients to a shared small profile

## Acceptance Criteria

Direct native-feature clients and news backend fixtures use one explicit 2-CPU 2-GiB memory and scratch profile without changing production defaults, assertions or explicit tight limits; original tiny helper stays unchanged. Native focused cases pass and one required code review closes all findings.


## Notes

**2026-10-28T15:28:03Z**

Code review APPROVE/no blocker or concern at codex-release2/review-native-budget/review.md for 345f..3c3f090c. Shared helper preserves the original tiny fixture and explicit tight limits. Three memory failures plus helpers: 10 passed in 70.56s after reducing shared batches to 8 MiB without increasing the 2 GiB ceilings. All affected native constructor functions and news backend fixtures: 45 passed in 681.32s. Reconciled reviewed 869; four CLI calls now pass the same limits through the existing reviewed option: CLI plus helpers 8 passed in 14.91s. No assertion or skip changes. Document-review, Explorer and Weekly wrapper limit forwarding remains engine-owned F5 follow-up cef-jh7i; this does not claim a whole-suite resource bound.
