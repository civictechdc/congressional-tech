---
id: ct-mrgt
status: open
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
