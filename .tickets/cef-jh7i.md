---
id: cef-jh7i
status: open
deps: []
links: [ct-5kto, ct-77zb, cef-96wc, ct-t906]
created: 2026-10-28T14:21:37Z
type: task
priority: 2
assignee: mikewolfd
---
# Review retained wrapper limits at the F5 strip

Lead141825 follow-up, not a local switch gate. At F5 determine whether ExplorerDocSpecWorkspace, WeeklyRetentionTables and sync-weekly survive. Delete only after accepted raw switch if legacy; for retained wrappers forward the existing NativeDatasets limits parameter and explicit CLI limits without changing defaults or bypassing native disk admission. Keep shared native-test profile coverage honest for remaining unbounded-by-selection callers; no skipped assertions or opaque binary wrapper.


## Notes

**2026-10-28T14:45:16Z**

Release CI-health triage also found scripts/qualify/document_review_catalog.py native-config constructor ignores its optional limits value. Review this retained wrapper with ExplorerDocSpecWorkspace, WeeklyRetentionTables and sync-weekly at F5; use the maintained NativeDatasets limits argument if retained. This followup is not the local switch gate (lead141825). News CLI forwarding is separately complete0e9af87c.

**2026-10-30T14:32:32Z**

Synced with ct-5kto (F5 18-group post-switch deletions under master epic ct-77zb).
