---
id: ct-5kto
status: in_progress
deps: [ct-t915, ct-yymr, ct-vnkf, ct-adtz, ct-klyz, ct-4jms]
links: [cefr-vnw8, cef-jh7i, cef-96wc]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, f5, cleanup, deletions, track6]
---
# T6.1 (F5): Execute 18-group post-switch legacy code deletions (~40k LoC) and retire seed_v5 & pipeline-data paths

Per docs/plans/bindings-20261025.md §6 and docs/plans/engine-first-switch.md item 7:
- Once deployment and new workflows are confirmed, run scripts/measure/cxb_switch_deletions.py and delete the 18 superseded congressional-tech groups (Python incremental catalog, Python rebuild path, legacy raw index, legacy viewer publication journal/v6 preparer, F0 converter, legacy e2e tests, etc.) one commit per group with before/after wc -l.
- Remove remaining seed_v5 / display_only branches (archive_seed_profile.py, archive_gate.py, archive_publish.py, archive_maintenance.py, archive-targets.mjs).
- Retire legacy pipeline-data/committee-explorer/public staging in .github/workflows/deploy-pages.yml and publish-explorer.yml.
- Rewrite apps/site/FILENAME-VIEWER.md and .github/workflows/raw-source-tables.md.

## Acceptance Criteria

All 18 superseded groups in cxb_switch_deletions.py are deleted one commit per group with before/after wc -l, seed_v5/display_only and pipeline-data staging paths are removed, FILENAME-VIEWER.md and raw-source-tables.md are rewritten, and all active test suites pass.


## Notes

**2026-10-30T15:21:37Z**

Phase A committed at f619d529: retired seed_v5/display_only branches (deleted archive_seed_profile.py + test, updated archive_publish.py, archive_maintenance.py, archive_gate.py, archive-targets.mjs), rewrote .github/workflows/raw-source-tables.md and apps/site/FILENAME-VIEWER.md, forwarded limits on retained wrappers (cef-jh7i), and resolved deleted glob/partial seeds in cxb_switch_deletions.py (unresolved=0 across G01-G18).

**2026-10-30T15:56:37Z**

Executed self-contained per-group F5 deletions: 1e780f1e (G06: wc -l 3991 -> 430, -3487 net, replaced by viewer_publication.archive_publish) and 8978b3bb (G12: wc -l 2625 -> 252, -2373 net, replaced by corpus_recovery.reconcile). 246 focused tests pass.
