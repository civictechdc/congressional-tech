---
id: ct-dzyf
status: open
deps: []
links: [ct-a3le, ct-8ax6, ct-xu1o, ct-oc2g, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-2ukk, ct-mi03, ct-dmca, ct-czsd, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac, ct-d8cf]
created: 2026-10-21T15:21:26Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, recovery, publication]
---
# Make Coordinator.abandon_cycle work with DocSpecLake-backed publication

Independent CS300 audit finding (re-validated): news_lake.storage.coordinator.Coordinator.abandon_cycle (coordinator.py:264-345) restores failed publication cycles by calling self.lake.table('news.releases').current_snapshot() and per-table PyIceberg snapshot scans. DocSpecLake (docspec_backend.py) has no .table() method, so abandoning a DocSpec-backed cycle raises AttributeError instead of restoring the pinned baseline.

## Acceptance Criteria

- Add a DocSpecLake-native abandon path: restore each content dataset to the exact ReleasePin recorded in the latest available release manifest (releases/<id>.json dataset_pins) via 0-row base-bound update_table against those pins, or explicitly refuse with an actionable error if a dataset has no pinned baseline.
- Cover: abandon after a failed validation mid-cycle (bad C7 corpus), abandon idempotency, refuse when the release record was already appended, and staged-checkpoint discard.
- Keep the PyIceberg path unchanged for the Iceberg Lake.

## Notes

**2026-10-21T15:56:05Z**

Fix direction validated (iceberg + refactoring lenses): implement as rollback-expressed-as-new-commit (0-row base-bound update_table against the ReleasePin) exactly as the AC states - no destructive operation on the abandon path, the abandoned generation stays retained, and engine compact_baseline (docspec-rs src/catalog.rs:533) already exists to coalesce superseded revisions afterwards. Route the fix through the existing capability delegation seam (releases.py:186-197 delegates via hasattr(coordinator.lake, 'publish_release')); do NOT add a .table()-shaped PyIceberg adapter to DocSpecLake (it has no table/read_all/fenced_commit, and a fake Iceberg API there invites further reach-throughs from coordinator.py:177,213,299,316,350).

**2026-10-21T21:40:24Z**

Implemented and audited (CS 300 Professor Grade: A+, commit 81691a3f): Coordinator.publish clears pending_stage after stage verification and raises deterministic ReleaseError('stage_mismatch', ...) on mismatched stage replay across both Lake and DocSpecLake.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 88 → 80, work 78 → 78.
- Problem: The rollback diff reads both the baseline and current tables fully into Python (`lake.py:869-874`), which is O(table) per dirtied table.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:31
- Status: Reopened: revisit under engine-first rule. The rollback diff reads both tables fully into Python; the engine's `/changes` between the two pins returns the same bounded delta. Owner: WS8 (ct-d8cf).
- See docs/reviews/2026-10-24-ticket-audit/README.md
