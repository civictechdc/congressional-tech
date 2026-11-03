---
id: ct-fh62
status: closed
deps: []
links: [ct-qg8e]
created: 2026-11-02T00:36:42Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [release, phase2]
---
# Decide whether empty caption tracks are published

5 recordings publish tracks with the SHA-256 of empty input, 2 new in 448651e7. Raw reads show the source returned an empty body, so nothing real is hidden. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

The owner decides whether an empty capture is a track, and a native check enforces it.


## Notes

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: empty caption bodies are not tracks; same rule as ct-3l1c. A native check refuses a published track whose body is the SHA-256 of empty input.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Besides the native track check, empty-body provider JSON wrappers must fail too (7 rows); otherwise 1 KB wrappers become tracks for R0h33K7rw7Q and Mv5g5Bn4AD8. impl-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): empty_body_tracks check plus the provider-envelope rule; 5 empty tracks drop, each read raw.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
