---
id: cefr-qw43
status: closed
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


## Notes

**2026-10-29T00:57:54Z**

Fixture-first reader-preservation case failed before9473b909 and the complete switch inventory lane passed20 cases. Inventory at9473b909 reproduces byte-identically and verifies stale=false;616 files/129336 population lines/18 groups. Immutable shared packet switch-inventory-ad99d156; actual deletions remain switch-owner actions and must be regenerated at the final combined head.
