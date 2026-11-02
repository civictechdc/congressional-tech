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


## Notes

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: empty caption bodies are not tracks; same rule as ct-3l1c. A native check refuses a published track whose body is the SHA-256 of empty input.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Besides the native track check, empty-body provider JSON wrappers must fail too (7 rows); otherwise 1 KB wrappers become tracks for R0h33K7rw7Q and Mv5g5Bn4AD8. impl-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): empty_body_tracks check plus the provider-envelope rule; 5 empty tracks drop, each read raw.
