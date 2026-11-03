---
id: ct-mrgt
status: closed
deps: []
links: [ct-d0o0]
created: 2026-11-02T04:01:45Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [captures, tests, phase2]
---
# Stop capture_fixture_coverage.py monkeypatching projection

capture_fixture_coverage.py monkeypatches projection. Expose the paths in the batched version move, since captures.py is byte-hashed.

## Acceptance Criteria

Coverage reads exposed paths with no monkeypatch.


## Notes

**2026-11-02T13:54:36Z**

2026-11-02 (lead): source_paths()/item_paths() exposed; no monkeypatch.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
