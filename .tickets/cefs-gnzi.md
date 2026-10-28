---
id: cefs-gnzi
status: closed
deps: []
links: []
created: 2026-10-28T10:21:44Z
type: task
priority: 0
assignee: site
tags: [engine-first, F1]
---
# Use main shared writer lock for every archive and legacy R2 writer

Owner/lead092220: exact main raw-source-mirror concurrency queue:max for archive publish/backfill/maintenance/capture and old weekly/publisher writers. Keep operation/namespace guards and read-only Pages exemption; no workflow dispatched. Coordinate raw fixture owner for old exceptions.

## Acceptance Criteria

All writer workflows use exact main common group/noncanceling/maxqueue; strict workflow fixture enforces it without old exceptions; focused local workflow checks pass and no live action.


## Notes

**2026-10-28T11:34:15Z**

Local done-when met: exact shared main raw-source-mirror concurrency/max queue enforced for every raw/archive/legacy writer; 61 focused checks pass in 2.94s; ONE CODE review APPROVE with no findings (codex-site/review-writer-lock/review.md). No workflows dispatched; hosted scheduling/live activation remain owner gates.
