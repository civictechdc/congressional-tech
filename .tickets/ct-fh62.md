---
id: ct-fh62
status: open
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

