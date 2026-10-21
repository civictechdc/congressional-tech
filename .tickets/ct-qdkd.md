---
id: ct-qdkd
status: closed
deps: [ct-n7la, ct-egpe]
links: [ct-a70m, ct-m9td, ct-egpe, ct-nc7l, ct-3faj, ct-wmtx, ct-lcbc, ct-gfv8]
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Show reusable native work and total resource use to operators

Connect NativeDatasets plan/inspect and retained_producer_inputs to the existing operator path. Report reusable preparation/native phases, actionable failure and combined disk headroom without another scheduler or lifecycle ledger.

## Acceptance Criteria

- Show exact operation/input/release IDs, current phase, completed reusable work, outstanding producer files and their measured bytes, with no credentials.
- Include preparation, derivative, spill, native scratch and headroom costs; distinguish actual byte/RSS/provider counters from estimates or unavailable values.
- Inspect metadata/file counts and history growth once at the relevant boundary. Link measured layout/compaction pressure to the protected maintenance plan; no automatic tuning or deletion.
- Test pending/completed/failed and lost-response states, configuration mismatch and early capacity refusal without corpus scans.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit updated dependencies to explicitly include closed `ct-n7la` (`native_capacity.py`) alongside `ct-q968` (`NativeDatasets.inspect` / `retained_producer_inputs`).


**2026-10-20T22:19:30Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-20T23:32:30Z**

Evolutionary-refactoring audit note at `main` (`8221566d` / `6cd80b0e`): `inspect_operator_status` (`packages/congress_api/src/congress_api/retention/native_capacity.py:218-260`) delegates to `native.retained_producer_inputs()`. When `ct-egpe` adds `NativeDatasets.update_table` custody, ensure `retained_producer_inputs()` and `_inspect_producer_inputs()` account for both `replacements` (`source.parquet`) and `deletions.parquet` byte sizes.
