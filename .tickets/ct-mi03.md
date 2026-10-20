---
id: ct-mi03
status: in_progress
deps: []
links: [ct-2ukk, ct-czsd]
created: 2026-10-20T18:24:28Z
type: epic
priority: 1
assignee: mikewolfd
tags: [docspec, efficiency, debt]
---
# Reuse DocSpec execution and recovery instead of duplicating it

Reduce import staging, process and read-copy overhead while preserving source values, document identities, mappings, reviews and coherent application selection. Keep primary UI edits isolated. Local qualification and production adoption remain separate.

## Acceptance Criteria

Measured before/after evidence, failure-path tests and independent review for each implemented child. Merge reviewed work and retain evidence before cleanup. Features without R2 support remain explicit dependent work; no unsupported operation is silently enabled.

