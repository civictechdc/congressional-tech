---
id: ct-saqg
status: open
deps: []
links: [ct-4jms, ct-z4w5]
created: 2026-11-14T15:56:14Z
type: bug
priority: 2
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Handle an absent attempted journal in native capture planning

A seven-target reviewed refetch plan failed at native step21/due with SanityCheckPlan UnknownPartitioning(0) when attempted=None produced an empty JSON input with zero partitions. Supplying a real empty gzip journal avoided that failure. This is an input-shape defect, not a publisher refusal. No request ran in the failed plan.

## Design

Use maintained empty-input handling without fabricating an attempted URL or relaxing native validation. Preserve unattempted, attempted, completed and refused distinctions. Evidence is repairs/source-refetch-20261114/scheduler-followup/plan_reviewed-empty-schema-failure.py, run.log and watchdog.json under the main durable archive root.

## Acceptance Criteria

Reproduce with the pinned native engine and no journal; prove an absent/empty journal yields the same due queue as an explicit empty file; preserve nonempty attempts and cutoff accounting; add a focused meaningful regression and named native result under unchanged limits.

