---
id: cefr-sp8z
status: in_progress
deps: []
links: []
created: 2026-10-28T15:50:29Z
type: task
priority: 2
assignee: raw
parent: cefr-7sar
---
# D1: release comparison intermediates before the full oracle join

The current native comparator retains fourteen materialized relations until job end. Release consumed inputs and retain bounded counts and old-only evidence so the full old-index comparison can fit without changing any row decision.

## Acceptance Criteria

A native bounded-memory fixture fails before the change and passes afterward; all comparator behavior checks pass; one independent code review approves; no captures mapping identity changes.

