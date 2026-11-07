---
id: ct-5kto
status: in_progress
deps: [ct-t915, ct-yymr, ct-vnkf, ct-adtz, ct-klyz, ct-4jms, ct-gi01, ct-m104, cef-96wc, ct-x78c]
links: [cefr-vnw8, cef-jh7i, cef-96wc, ct-w8dc, ct-93zs, ct-m104, ct-t915, ct-gi01, ct-8kl2, ct-a3le, ct-082q]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, f5, cleanup, deletions, track6]
---

# Retire the old Explorer after the shared release is accepted

Remove the old Explorer publishing and Pages dependencies once users can get the retained research data from the shared archive release. The original 18 deletion groups and seed cleanup are complete. At the November 5 audit, GitHub reported the old writer workflow disabled. The active Pages build still stages its retained output, and the deployed dashboard still reads the old pointer. The narrow retirement is to remove those callers and the superseded publication wiring after the accepted replacement is live.

## Acceptance Criteria

- Use the preservation and production evidence from `ct-gi01`, old witness row dispositions from `ct-x78c`, shared site and MCP reads from `ct-t915` and `ct-m104`, and live switch and rollback handoff from `cef-96wc`. Retire the old path immediately after accepted live cutover under the existing switch order. [Phase 2 order](../docs/plans/phase-2-annex-20261028.md#46-explorer-migration-and-data-coverage)
- Remove the superseded writer and its active callers, scratch paths, second pointer consumption, and `pipeline-data/committee-explorer/public` staging in `publish-explorer.yml` and `deploy-pages.yml`. Check actual workflow commands and remaining consumers of `CURRENT.json` and the event map. Old dashboard record links keyed by UUID must show the existing policy's removal notice.
- Preserve raw inputs, provenance, legacy-only facts, protected historical releases, and the exact artifacts and application revision needed for rollback. Trace mixed files to their current callers. Keep the independent YouTube coverage page, its report data, and required utilities. Check broader workspace package deletion separately where it changes `uv.lock` and thereby lake parser pins. Keep that parser-version decision separate from removing the old publication wiring.
- Update the maintained workflow and reader instructions. Record focused checks and the required combined regression for implementation changes. Verify the shared site and MCP against the accepted release after retirement, including old UUID behavior and the retained YouTube report.

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

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

**2026-11-02T13:05:13Z**

2026-11-02 (lead): Round 3 plan at .cache/rounds/r3/plan.md. Retirement removes about 11,100 site lines, 11,056 Python source lines and 1,678 test lines, plus 9,297 lines in 43 mixed test files reviewed case by case. Keep apps/committee_youtube/data, offline-python.py and components/dashboard/ (the YouTube coverage page). The 20 GB swap step was already removed in f545385b. Decision: old dashboard links naming a record by UUID show a removal notice, with no ID mapping, following the ct-ktfe precedent and the ct-tk10 link rule.

**2026-11-02T13:54:36Z**

Owner decision 2026-11-02: retire the old Explorer right after live acceptance, with no overlap period.

**2026-11-02T14:50:56Z**

2026-11-02 (lead): r3-retire paused at 0b462cfe (G19 inventory, workflows, lock, Python deletions, page_metadata in its own commit). Removing workspace members regenerates uv.lock, which every parser_version hashes, so all six pins move with no parser change; fix by narrowing parser-version hashing to imported dependencies (greybeard advisory) before retirement merges.

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: retire the old Explorer route and staging as soon as /dashboard/ moves to the release (ct-t915); no overlap period.

**2026-11-05T17:11:15Z**

Consolidated ownership from ct-8kl2/ct-98sm: retain completed G01/G02 and later deletion evidence, then retire only remaining old writers, pointer consumption, scratch/call paths and staging after native/site/MCP/live acceptance. Preserve source data, evidence and rollback references; archived tracker closures are not a new live-switch or retirement proof. ct-a3le's diagnostic research import remains standalone and linked, not an added Phase 2 exit gate.

**2026-11-06T18:43:09Z**

All independent retirement preparation is complete at b343b1c6e58be97bd7605a2d8979cf5d54af07b8; the reviewed branch is unchanged and clean. The isolated patch removes the old writer and Pages staging, shows removal notices for old UUID bookmarks, and preserves event-ID forwarding, YouTube coverage, historical data and rollback references. G01–G18 remain credited as complete. Validation: 23 focused workflow tests, 108 reader tests, the static build and the complete Pages browser helper passed, including saved-copy isolation, memory and historical witness-link checks. The earlier broader run's unchanged capture-fixture failure remains documented for combined regression. Evidence: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-5kto/{HANDOFF.md,completion-audit.json,completion-pages.log}.

Keep open: the root coordinator owns integration and combined regression; ct-m104 owns the final native candidate and deployment; cef-96wc owns accepted live cutover, paired rollback references and post-retirement readback with the release owner. Local preparation is not merged or live retirement.

Independent review: REQUEST CHANGES; current owner state: repair in progress. These findings remain open until repaired and rechecked. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-5kto/REVIEW.md).

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at de16b440. The review caught loss of the weekly YouTube report deployment handoff when retiring the old publisher. The repair restores that handoff while preserving revision-specific checkout, browser/upload gates, bookmark forwarding and rollback material. The new regression failed before repair; 24 focused workflow checks passed afterward.

This reviewed follow-up is not yet included in local main. Remaining: Authentic collector-to-Pages execution, cef-96wc live cutover acceptance, paired rollback references and post-retirement readback. Retirement remains conditional. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-5kto/REVIEW.md).

**2026-11-07T21:42:56Z**

The accepted November 7 archive and site now supply the retirement boundary. The pre-retirement Pages run 42410703083 used application 8d3ab43ba3213401074163c7c94bb155722e0661 and pipeline-data 5462f013e69a73876f27a588e63e4a2a960dddb6. Both exact revisions are preserved under refs/archive/finish-merge-prune-20261107/rollback; the prior e145 archive remains retained. Independent live checks confirmed an event bookmark, YouTube coverage and hosted MCP on 5d24699ad9fa. The old writer is disabled with no queued or running jobs.

Integrated both reviewed retirement commits b343b1c6 and de16b440, preserving current main's capture-fixture and testimony controls. Removed three stale Congress API test assertions that still read the deleted writer, and marked its old implementation document as historical. The combined focused Python selection passed all 51 checks (partial lane); all 111 site reader tests and the static build passed. No model, parser, runtime, root lock, MCP package or stored-data deletion is involved. The generated local legacy staging copy was moved to retained rollback material.

Evidence: .cache/archive-release/finish-merge-prune-20261107/. Post-retirement deployed browser/MCP readback follows the Pages deployment. The next normal weekly collector completion remains the authentic check of its new Pages trigger; this cleanup does not launch unrelated acquisition.

**2026-11-07T21:50:36Z**

Retirement is merged, pushed and deployed at 58c138d87a75d7338a750e65816956435b1c381c. Pages run 42417261480 passed on that exact revision. The complete maintained local browser helper passed, alongside the 51 focused Python checks and 111 site reader checks already recorded.

Independent post-deployment acceptance passed: event 100520 opened the current hearing on archive 5d24699ad9fa; the authentic legacy UUID showed the removal notice and its search link opened that same release; there were zero legacy data requests. The separate old event-map request returned 404. The YouTube CSV returned 200 and its filters/leaderboard rendered. Hosted MCP returned the same event/title/release. Evidence: .cache/archive-release/finish-merge-prune-20261107/post-retirement-live.json. The accepted archive data and MCP package did not change.

Implementation and live retirement checks are complete. This ticket remains open only to observe the next normal weekly collector completion triggering Pages, as required by its retained operating acceptance. That future event does not require retaining the merged implementation branch/worktree or repeating the native archive build.

**2026-11-07T22:30:56Z**

November 7 post-release owner update for archive 5d24699ad9fa / Explorer 0.6.2. Retirement from 58c138d8 is deployed and accepted: current event bookmarks, old UUID notices, zero legacy-data requests, YouTube and hosted MCP all passed. The owner verified current GitHub run history; the latest Pages run was push-triggered.

Keep in_progress only for the first normal weekly collector completion to trigger Pages. The next eligible scheduled start is November 7 at 7:00 p.m. EST. Close after the actual scheduled collector and successful downstream Pages run are recorded and their deployed YouTube report is verified. A manual run does not establish this criterion. [Owner evidence](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-5kto/STATUS.json).
