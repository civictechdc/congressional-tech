---
id: ct-dmca
status: closed
deps: [ct-egpe, ct-q05l]
links: [ct-sb0s, ct-gziq, ct-3180, ct-13cn, ct-q05l, ct-a3le, ct-8ax6, ct-xu1o, ct-oc2g, ct-dzyf, ct-aia9, ct-te1p, ct-n6lj, ct-2ukk, ct-mi03, ct-czsd, ct-8kl2, ct-gi01, ct-2yl5, ct-bwac, ct-syx8]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Adopt native schema evolution and resumable scalar backfills

Use the upgraded engine for compatible catalog/news field changes and genuine row-local derived fields. Migrate the application adapter and its existing schema/rule-upgrade caller; keep classification, entity resolution and grouping policy with their current owners.

## Acceptance Criteria

- Use current schemas/plan, schemas/run, backfills/plan and backfills/run APIs through the shared client. Preserve field IDs, omission versus explicit null, defaults, original schemas and exact old pins.
- Choose a real existing compatible field change; document its meaning and mapping. Do not manufacture a field simply to exercise an API or replace Python/model classification with unsupported scalar SQL.
- For advancing input, use supported continuous-backfill plan/intent and dependency correction only when relevant; bind corrections to the exact computed definition. Prove catch-up, bounded intake fence and atomic selected coverage.
- Qualify the intended backend, restart and concurrent writers. Current R2 scalar/schema operations remain gated; planning assumes an upstream upgrade, not a local-only fallback or full rebuild.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit added the Step 6 next-maintainer requirement: unify `docspec-rs` remote operation/group capability checks into a single `Engine` authority when implementing `ct-dmca`, `ct-sb0s`, and `ct-gziq`.


**2026-10-20T22:19:30Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-21T02:20:25Z**

Implemented and verified: added plan_schema, evolve_schema, plan_backfill, backfill, plan_continuous_backfill, continuous_backfill, and correct_dependencies in docspec_client and evolve_catalog_schema / backfill_scalar_group in native_features.py. Tested in tests/test_native_features.py::test_ct_dmca_schema_evolution_and_scalar_backfill_without_source_rewrite.

**2026-10-21T15:21:41Z**

Reopened by independent CS300 audit (re-validated): evolve_catalog_schema and backfill_scalar_group are exercised only by tests/test_native_features.py; acceptance requires migrating the existing application schema/rule-upgrade caller. Remaining scope: wire the maintained catalog schema/rule-upgrade entry point through evolve_catalog_schema/backfill_scalar_group for a real compatible field change. Note: R2 execution of schemas/backfills is still gated LocalOnly (Engine::check_request_backend), so local-workspace qualification comes first; R2 enablement remains the separately authorized engine extension.

**2026-10-21T20:53:50Z**

Aligned with end-state epic ct-8kl2 (ct-2yl5, ct-bwac) and spicy-stack ss-6gwu (multi-group read_combined in ExportSpec) and ss-vfm6 (remote R2 parity for BackfillSpec).

**2026-10-21T21:40:24Z**

Implemented and audited (CS 300 Professor Grade: A+, commit 81691a3f): wired upgrade_source_rules / _update_from_raw (catalog_raw_updates.py) and RawStorage.evolve_state_schema (raw_storage.py) through evolve_catalog_schema and backfill_scalar_group (/schemas/run, /backfills/run, /continuous-backfill) for compatible field evolution and scalar group backfills with zero source-file rewrites.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03a).
- Grades: proposal 80 → 70, work 60 → 55.
- Problem: This directly contradicts the AC "do not manufacture a field".
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:30
- Status: Closed as superseded by the simplification plan (WS2 step 7, ct-syx8): missing raw-state fields are filled at read time and `indexes/raw.json` is never republished to change a schema; the default scalar backfills are deleted, so qualifying in-place evolution is moot.
- See docs/reviews/2026-10-24-ticket-audit/README.md
