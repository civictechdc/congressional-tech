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


## Notes

**2026-10-27T04:35:50Z**

Contracts f790132a and 3c8c1d5f precede the cleanup binding 28fe4caa. Privacy-emitter contracts cf7d2914 precede the shared policy binding. 34 cleanup/adapter/import-fence, 50 privacy/archive and 25 recovery/native preservation checks pass. Full local mirror scan still running; all 2289 receipts copied into scratch first. No bucket read/write or live writer change.

**2026-10-27T05:45:03Z**

Local qualification complete: all 2289 scratch-copy receipts and 2596054 lines verified; 887 changed; final full scan has zero matches. 56 focused checks pass. Commands and safe report are committed under docs/measurements/engine-first-20261027/b0. Owner must confirm patterns, drain writers, run live cleanup and final rescan, then lock receipts/. No live storage accessed.
