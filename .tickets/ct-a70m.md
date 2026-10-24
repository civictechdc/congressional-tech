---
id: ct-a70m
status: open
deps: [ct-qdkd]
links: [ct-wmtx, ct-lcbc, ct-mpsp, ct-m9td, ct-egpe, ct-qdkd, ct-nc7l, ct-3faj, ct-gfv8, ct-syx8]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Protect application releases in native retention and restore planning

Wire native inspection/removal planning and restore prerequisites to application-selected catalogs, news releases and exports. Keep non-native caches, original captures and the application availability registry under their existing owners.

## Acceptance Criteria

- Translate supported old/current release pins, active readers, incomplete operations, pending producer inputs and export pins into protected native references. Never infer safety from an unreferenced local path alone.
- Present exact reclaimable/protected bytes and quiescence/restore prerequisites through the operator path; no automatic expiration or live deletion.
- If measured small-file pressure justifies compaction, qualify exact logical identity and old-reader preservation on an isolated fixture through the maintained API. Keep small tables unpartitioned until actual selective workload justifies supported date transforms.
- Exercise isolated restore/readback with retained locators and wrong namespace/generation refusals. Current R2 maintenance limitations remain explicit; no deployment or restore mutation is implied by planning.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit verified that `NativeDatasets.inspect_retention` and `plan_removal` are already wired on the persistent host adapter in `codex/docspec-host-transport` (`docspec.py:290-295`). Once `ct-q968` and `ct-qdkd` land, bind application-selected pins into the read-only operator retention planner and test protection invariants.


**2026-10-20T22:19:31Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: B+ (Closed for RunSpec pins). plan_protected_retention (native_capacity.py:361-465) protects application pins, exports, active readers, incomplete ops, and RunSpec producer inputs; UpdateSpec replacement/deletion custody and CLI/HTTP lifecycle compaction are tracked in ct-m9td and ct-gfv8.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03a).
- Grades: proposal 78 → 65, work 55 → 55.
- Problem: A latent correctness bug: objects the engine protects would be classified as reclaimable.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:21
- Status: Reopened: revisit under engine-first rule. The unmet criteria (feed application pins, honor native blockers) are not wanted; the owner wants the Python retention planner deleted entirely (`plan_protected_retention` and the retention-plan CLI mode) in favor of engine retention. Owner: WS2 step 6 (ct-syx8), after the guard test that no Python path deletes under raw prefixes.
- See docs/reviews/2026-10-24-ticket-audit/README.md
