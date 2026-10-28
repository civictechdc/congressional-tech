---
id: cefr-9gjq
status: in_progress
deps: []
links: []
created: 2026-10-28T12:53:45Z
type: bug
priority: 1
assignee: mikewolfd
---
# D1 scratch monitor tolerates vanished paths

Skip only vanished scratch directories or entries during allocated-byte accounting; retain non-ENOENT refusals and all resource ceilings. Deterministic real-filesystem race fixture before the fix; focused runner and one CODE review.

