---
id: ct-sb0s
status: open
deps: [ct-egpe, ct-q05l]
links: [ct-13cn, ct-q05l, ct-3180, ct-dmca, ct-gziq]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Attach provenance and review evidence through native receipt updates

Use native EvidenceSpec for a real occurrence-linked provenance or annotation consumer without rewriting source values. Source locators and document IDs remain application identities; map them explicitly to the exact native occurrence.

## Acceptance Criteria

- Add receipts/plan and receipts/run plus exact evidence reads to the shared client only for the chosen caller; bind every request to exact source and evidence versions.
- Preserve ordered duplicate receipts, nulls, original source bytes/locators/digests and source-document many-to-many mappings; receipt URLs do not retain external objects.
- Test source replacement/deletion and occurrence remapping. Preserve existing review decisions and recorded withdrawal reasons; never infer review authority from native row positions.
- Verify zero unchanged source rewrites, fresh-host replay and coherent application publication on the intended R2 profile. Keep unsupported groups explicit until engine qualification passes.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit linked `ct-sb0s` to `ct-dmca`'s unified `Engine` remote capability check and reinforced the zero-source-rewrite invariant.


**2026-10-20T22:19:30Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-21T02:20:25Z**

Implemented and verified: added NativeDatasets.update_evidence_table, read_receipts, read_evidence, read_occurrences in docspec_client and map_locators_to_occurrences / attach_occurrence_receipts / read_occurrence_receipts in native_features.py with zero source-byte rewrites. Tested in tests/test_native_features.py::test_ct_sb0s_attach_and_read_occurrence_receipts_with_zero_source_rewrites.

**2026-10-21T15:21:41Z**

Reopened by independent CS300 audit (re-validated): map_locators_to_occurrences / attach_occurrence_receipts / read_occurrence_receipts are exercised only by tests/test_native_features.py; acceptance requires one real occurrence-linked provenance/review consumer. Remaining scope: wire review provenance (e.g. source_observations receipt locators) through attach_occurrence_receipts against an exact pinned release, preserving duplicate receipts, review ownership, and zero source-byte rewrites. R2 receipts remain gated LocalOnly; local qualification first.
