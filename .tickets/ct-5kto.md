---
id: ct-5kto
status: open
deps: [ct-t915, ct-yymr, ct-vnkf, ct-adtz, ct-klyz, ct-4jms, ct-gi01, ct-m104, cef-96wc]
links: [cefr-vnw8, cef-jh7i, cef-96wc, ct-w8dc, ct-93zs, ct-m104, ct-t915, ct-gi01]
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

## Remaining scope — 2026-10-30 reconciliation

Reopened at the user's request. Keep the completed G01-G18 deletion evidence;
there is no instruction to repeat those deletions. The remaining failure is
pipeline-data/committee-explorer/public staging in both publish-explorer.yml and
deploy-pages.yml, together with the separate Explorer publishing route. The
required sequence and preservation checks are in docs/plans/phase-2-annex-20261028.md §4.6 and
docs/plans/engine-first-switch.md, Remaining phase-2 Explorer switch.

## Acceptance Criteria

- Retain the earlier G01-G18, seed_v5/display_only and documentation results; verify any remaining applicable criteria without repeating completed work.
- ct-gi01's field-preservation mapping and native producer, ct-t915's unified consumer, ct-m104's data coverage and cef-96wc's live switch have accepted evidence before deleting their old replacements.
- Remove the separate Explorer writer/pointer consumption and pipeline-data/committee-explorer/public staging from both publishing workflows. Check active imports, commands and callers rather than only the deletion-group count.
- Preserve raw inputs, provenance, legacy-only facts now retained by the replacement, and rollback references. Do not erase historical releases merely to remove their live consumers.
- Update maintained workflow/reader documentation and verify the shared site/MCP release after retirement, with focused checks and the required combined regression for implementation changes.

## Notes

**2026-10-30T15:21:37Z**

Phase A committed at f619d529: retired seed_v5/display_only branches (deleted archive_seed_profile.py + test, updated archive_publish.py, archive_maintenance.py, archive_gate.py, archive-targets.mjs), rewrote .github/workflows/raw-source-tables.md and apps/site/FILENAME-VIEWER.md, forwarded limits on retained wrappers (cef-jh7i), and resolved deleted glob/partial seeds in cxb_switch_deletions.py (unresolved=0 across G01-G18).

**2026-10-30T15:56:37Z**

Executed self-contained per-group F5 deletions: 1e780f1e (G06: wc -l 3991 -> 430, -3487 net, replaced by viewer_publication.archive_publish) and 8978b3bb (G12: wc -l 2625 -> 252, -2373 net, replaced by corpus_recovery.reconcile). 246 focused tests pass.

**2026-10-30T17:46:00Z**

Completed all 18 F5 deletion groups (G01-G18) on main (-58,500+ net lines removed):
- G01: 703a5920 (-19,820 net)
- G02: df1bed37 (-16,603 net)
- G03: c25ee9bb (-9,493 net)
- G04: 14dbae1e (-309 net)
- G05: 4dce6edc (-417 net)
- G06: 1e780f1e (-3,487 net)
- G07: 7ee01ac7 (filename_viewer.py deleted)
- G08: 4c78d1ee (-198 net)
- G09: 41c7112c (pipeline_status.py deleted)
- G10: dd9a5f12 (-477 net) + 176cd4a1 (-109 net, docspec.py & docspec_host.py shims deleted)
- G11: 0c281563 (-1,467 net)
- G12: 8978b3bb (-2,373 net)
- G13: 9b387f85 (-8,107 net)
- G14: 41c7112c (apply-r2-edge-rules.py deleted)
- G15: a0eaac9a (-2,147 net)
- G16: 9225ac8b (-411 net)
- G17: 72dd4975 (tests/e2e deleted)
- G18: cb19315b (-186 net)
- Plus 3014737a (zero PYTEST_CURRENT_TEST ratchet across all packages/*/src/**/*.py) and 32a1a3c6 (cxb_switch_deletions.py SITE path update).
Verified with pytest across congress_api, viewer_publication, docspec_client, corpus_recovery, committee_youtube, and scripts/measure.

**2026-10-30T20:37:05Z**

Reopened and reconciled at the user’s request on 2026-10-30. Current scope and acceptance above supersede the earlier closure where it claimed the remaining Explorer migration was complete. Canonical coverage and order: docs/plans/phase-2-annex-20261028.md §4.6. No implementation, live publication or deletion was performed by this reconciliation.
