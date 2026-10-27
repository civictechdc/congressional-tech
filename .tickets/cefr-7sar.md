---
id: cefr-7sar
status: in_progress
deps: []
links: []
created: 2026-10-27T17:09:26Z
type: task
priority: 2
assignee: raw
---
# D1: rebuild captures from every receipt shape through native jobs

Owner reassigned D1 to raw in run2. Follow current DM6.1; message engine before changing a column or rule.

## Acceptance Criteria

Native receipt mapping covers all shapes and status/time/completeness; rebuild-equivalence passes; pinned old-index comparison has written transformations and lists owner-only rows; local append races covered; live lake writes owner-gated.

