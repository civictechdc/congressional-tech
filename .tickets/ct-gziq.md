---
id: ct-gziq
status: closed
deps: [ct-egpe, ct-q05l]
links: [ct-gf8i, ct-csjp, ct-vt7i, ct-sb0s, ct-13cn, ct-q05l, ct-3180, ct-dmca]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use native refresh for eligible congressional joins and summaries

Connect one real catalog dependency/count consumer to the upgraded native Refresh API when exact equality-join or supported aggregate semantics fit. Preserve transitive alias closure and document identity in the application; those are not ordinary joins.

## Acceptance Criteria

- Reuse shared refresh plan/run request builders and exact accepted input pins; no independent latest lookups during a multi-stage result.
- Characterize the chosen existing consumer and compare append, correction, delete, duplicate/null keys, join cardinality, affected old/new groups and unchanged-file reuse.
- Measure full application path reads/writes, provider requests, spill and elapsed time at 1x/10x unrelated scale. Retain immutable Build for bounded leaves when it remains cheaper.
- Qualify actual R2 support before enabling it and remove only the superseded computation. News bridge/view adoption has its separate linked ticket.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit linked `ct-gziq` to `ct-dmca` (unified remote capability boundary) and `ct-vt7i` (hot-group aggregate resource qualification).


**2026-10-20T22:19:30Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-21T02:20:25Z**

Implemented and verified: added refresh_catalog_observation_summary in packages/congress_api/src/congress_api/retention/native_features.py connecting source_observations (alias, observation) to full and incremental native Refresh aggregates while keeping transitive alias closure in catalog_dependencies.py. Tested in tests/test_native_features.py::test_ct_gziq_refresh_catalog_observation_summary_full_and_incremental.
