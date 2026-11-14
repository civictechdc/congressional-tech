---
id: ct-saqg
status: in_progress
deps: []
links: [ct-4jms, ct-z4w5]
created: 2026-11-14T15:56:14Z
type: bug
priority: 2
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Handle an absent attempted journal in native capture planning

The absent-journal fix is implemented and independently checked at integrated commit 4189d523. A real empty native input now represents an unattempted run without inventing a URL. Focused scheduler tests and the exact seven-target native replay pass; merge acceptance remains.

## Design

Use maintained empty-input handling without fabricating an attempted URL or relaxing native validation. Preserve unattempted, attempted, completed and refused distinctions. Evidence is repairs/source-refetch-20261114/scheduler-followup/plan_reviewed-empty-schema-failure.py, run.log and watchdog.json under the main durable archive root.

## Acceptance Criteria

Reproduce with the pinned native engine and no journal; prove an absent/empty journal yields the same due queue as an explicit empty file; preserve nonempty attempts and cutoff accounting; add a focused meaningful regression and named native result under unchanged limits.


## Notes

**2026-11-14T17:16:28Z**

Implementation 36af6fe2 is integrated as 4dfa38fe. The 107-case scheduler file passes, including absent/empty/nonempty attempt cases. Root checked the final source and reran a real native consumer at integrated commit 4189d523 after markup integration. Durable proof is source-refetch-20261114/scheduler-followup/maintained-planner-fix/{root-review-due-candidates,root-integration-review}. No publisher request or catalog write occurred during validation.
