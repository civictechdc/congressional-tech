---
id: cefr-qw43
status: in_progress
deps: []
links: []
created: 2026-10-29T00:51:17Z
type: task
priority: 1
assignee: raw
---
# F5: preserve the maintained D2 readers in the switch split

The reviewed completion/prefetch changes added maintained raw-reading helpers. Make the switch inventory explicitly preserve their modules and R2 methods, then regenerate at the committed head. The generator remains read-only; no live imports are deleted.

## Acceptance Criteria

A fixture fails against the old preservation list; the focused switch lane passes; a current-head inventory verifies fresh and has an immutable handoff. No deletion is applied.

