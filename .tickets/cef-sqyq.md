---
id: cef-sqyq
status: in_progress
deps: []
links: []
created: 2026-10-27T04:27:05Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, B0]
---
# B0: sanitize older receipts with backup and exact readback verification

## Acceptance Criteria

Scanner reports every nested header/path occurrence; local rewrite preserves URLs, links, pointer targets and uncut line bytes, verifies a private backup before CAS, survives a crash after CAS, records each receipt, and final scan is clean. Owner approves patterns, drains writers, rewrites live receipts and locks receipts/.

