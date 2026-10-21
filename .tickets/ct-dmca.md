---
id: ct-dmca
status: open
deps: [ct-egpe, ct-q05l]
links: [ct-sb0s, ct-gziq, ct-3180, ct-13cn, ct-q05l]
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
