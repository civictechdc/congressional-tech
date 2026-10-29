---
id: can-vqiy
status: closed
deps: []
links: []
created: 2026-10-29T12:02:24Z
type: task
priority: 1
assignee: engine
---
# Land scoped Linux fanout fixture timeout on main

Reproduce only faa8b412 fixture-scoped native.timeout=300 and existing context cleanup on exact published main92118. Existing Linux0cb affected PASS on10d is historical and source-specific; no global timeout, memory, scratch, assertion, SQL or runtime change.

## Acceptance Criteria

Exact faa patch and AST/file identity verified; focused official-runner checks pass on isolated main-based branch under4GiB after active nativeprobe43104 ends; lead receives branch/base/commit and PR body+commands; no outward effects.


## Notes

**2026-10-29T12:05:52Z**

Focused official-runner check on main92118 plus exact faa8b412 file:4 passed0 failures/errors/skips53.45s; monitored57.988s/2608992408B charged physical<4GiB, no failure/cleanup errors. Full file/AST and diff byte-identical to faa8b412. Historical Linux0cb source10d affected1P remains explicitly source-specific, not freshmainLinux qualification. Main-based PR handoff prepared; no outward effects. No extra formal review required for this test-only patch per engine protocol decision.
