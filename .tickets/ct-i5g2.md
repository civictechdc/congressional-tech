---
id: ct-i5g2
status: open
deps: []
links: []
created: 2026-10-24T18:46:38Z
type: chore
priority: 3
assignee: mikewolfd
parent: ct-syx8
tags: [audit-20261024, efficiency]
---
# Small efficiency cleanups on the raw path

Efficiency pass E12: a receipt LIST per run (raw_archive.py:672, O(R)); RecoveryGuard stats all pinned files per write (guards.py:101-113, O(W*P)); MD5 computed twice per put (r2.py:112,128); the native-manifest cache skips uploads on same-size files and isn't scoped by bucket (immutable_metadata.py:85-93, r2.py:212-217,341-351).

## Acceptance Criteria

- Receipts are listed from a cursor.
- The guard checks once per run.
- MD5 once per put.
- Manifest uploads rely on create-only PUTs instead of the size cache.

