---
id: ct-ktfe
status: open
deps: []
links: [ct-qg8e]
created: 2026-11-02T00:36:42Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, phase2]
---
# Every witness_key changed with no published mapping

0 of 147,048 previous witness_keys survive in 448651e7. The redefinition is deliberate (annex §4.7, GB5), but consumers holding old keys break and no mapping is published. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

The owner decides whether to publish a mapping, and the release notes state the decision.


## Notes

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: release note only. No old-to-new witness_key mapping; the release notes state that witness IDs changed and old ?witness= links no longer resolve.
