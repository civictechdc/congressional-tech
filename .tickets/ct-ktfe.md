---
id: ct-ktfe
status: closed
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

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): Witness-ID notice written to docs/releases/README.md on r1b-h; per-release notes render from cause records.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
