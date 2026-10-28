---
id: cef-jh7i
status: open
deps: []
links: []
created: 2026-10-28T14:21:37Z
type: task
priority: 2
assignee: mikewolfd
---
# Review retained wrapper limits at the F5 strip

Lead141825 follow-up, not a local switch gate. At F5 determine whether ExplorerDocSpecWorkspace, WeeklyRetentionTables and sync-weekly survive. Delete only after accepted raw switch if legacy; for retained wrappers forward the existing NativeDatasets limits parameter and explicit CLI limits without changing defaults or bypassing native disk admission. Keep shared native-test profile coverage honest for remaining unbounded-by-selection callers; no skipped assertions or opaque binary wrapper.

