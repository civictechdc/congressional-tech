---
id: ct-saqg
status: closed
deps: []
links: [ct-4jms, ct-z4w5]
created: 2026-11-14T15:56:14Z
type: bug
priority: 2
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Handle an absent attempted journal in native capture planning

PR #170 merged at e6a91fdb2338db13216bba6aea2567b182a6ac22 after both CI workflows passed. The planner now represents an absent attempted journal as an actual empty native input. The 107 scheduler cases and independent exact native consumer checks pass under unchanged limits.

## Design

Use maintained empty-input handling without fabricating an attempted URL or relaxing native validation. Preserve unattempted, attempted, completed and refused distinctions. Evidence is repairs/source-refetch-20261114/scheduler-followup/plan_reviewed-empty-schema-failure.py, run.log and watchdog.json under the main durable archive root.

## Acceptance Criteria

Reproduce with the pinned native engine and no journal; prove an absent/empty journal yields the same due queue as an explicit empty file; preserve nonempty attempts and cutoff accounting; add a focused meaningful regression and named native result under unchanged limits.


## Notes

**2026-11-14T17:16:28Z**

Implementation 36af6fe2 is integrated as 4dfa38fe. The 107-case scheduler file passes, including absent/empty/nonempty attempt cases. Root checked the final source and reran a real native consumer at integrated commit 4189d523 after markup integration. Durable proof is source-refetch-20261114/scheduler-followup/maintained-planner-fix/{root-review-due-candidates,root-integration-review}. No publisher request or catalog write occurred during validation.

**2026-11-14T18:47:48Z**

Closed after PR #170 merge and passing CI. Exact integrated consumer proof at 4189d523 and unchanged scheduler bytes remain in source-refetch-20261114/scheduler-followup/maintained-planner-fix/root-integration-review/review.md. No publisher request or catalog write was needed to qualify this fix.
