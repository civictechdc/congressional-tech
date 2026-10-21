---
id: ct-13cn
status: open
deps: [ct-egpe, ct-q05l, ct-9few]
links: [ct-3180, ct-sb0s, ct-q05l, ct-dmca, ct-gziq]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use native changes for catalog diagnostics and selective downstream work

Expose the current POST /compare and POST /changes APIs through NativeDatasets and wire an actual catalog diagnostic/change consumer. Use exact versions and the maintained native change certificates instead of another full-population change ledger.

## Acceptance Criteria

- Preserve duplicate-aware value versus occurrence identity, typed added/removed members, nulls and schema/evidence/coverage-only effects. Compare with a small independent multiset reference.
- Consume one change stream and derive counts from it when rows are required; do not run compare and changes redundantly. Check stream completeness and exact source pins.
- Feed only proven changed scope to existing dependency/viewer logic. Native value differences do not replace source identity, transitive grouping or review binding policy.
- Test missing/invalid history and bounded fallback handling; incremental callers refuse unbounded fallback with an actionable reason. Report actual read/returned bytes and support separately for each field group/backend.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit note: native remote `source`-group comparison and change streaming landed on `docspec-rs` `main` (`b240765`). Once `ct-3180` completes isolated R2 provider qualification and `ct-q968` lands, wire the Python diagnostic consumer through `NativeDatasets` + `ArrowResponse`.


**2026-10-20T22:19:31Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-21T02:20:25Z**

Implemented and verified: added NativeDatasets.compare, changes_batches, and read_changes in packages/docspec_client/src/docspec_client/docspec.py and inspect_catalog_changes in packages/congress_api/src/congress_api/retention/native_features.py. Tested in tests/test_native_features.py::test_ct_13cn_inspect_catalog_changes_preserves_duplicates_nulls_and_affected_keys.

**2026-10-21T15:21:41Z**

Reopened by independent CS300 audit (re-validated): acceptance requires wiring an actual catalog diagnostic/change consumer, but packages/congress_api/src/congress_api/retention/native_features.py is currently imported only by tests/test_native_features.py. Remaining scope: connect inspect_catalog_changes to a real caller (e.g. raw_changes/catalog dependency preparation feeding only proven changed keys, or an operator diagnostic command) and record read/returned bytes per field group; also fix the ct-9few descriptor field-name mismatch in the same pass.

**2026-10-21T15:56:05Z**

Refactoring-lens caution on remaining scope: an "operator diagnostic command" caller would manufacture a consumer to justify the adapter - the same anti-pattern ct-dmca's own AC forbids on the data side ("Do not manufacture a field simply to exercise an API"). Prefer migrating one existing, measured-expensive caller (e.g. raw_changes / catalog dependency preparation feeding only proven changed keys). If no existing caller justifies migration, the honest outcome is descope with the adapter retained as linked evidence. Closure evidence must cite the production caller at file:line, never a test file.
