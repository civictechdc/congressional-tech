---
id: cefr-yvjw
status: in_progress
deps: []
links: []
created: 2026-10-27T13:54:26Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B6: clean-tree identity for raw receipt writers

## Acceptance Criteria

Raw writers record clean HEAD and SHA256 of uv.lock; dirty tracked, staged and untracked files refuse before storage connection; source manifest shares identity; focused tests pass.

