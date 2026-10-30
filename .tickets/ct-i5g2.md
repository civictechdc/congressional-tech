---
id: ct-i5g2
status: closed
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


## Notes

**2026-10-30T16:52:15Z**

Verified completed across cef-s4vp, cefr-9zd4, ct-fcwp (commit cd2e81a7), and F5 G12 (commit 8978b3bb): BodyStore computes Content-MD5 once per create-only PUT, raw_verifier.py lists receipts incrementally from baseline cursors, and legacy RecoveryGuard (guards.py) was deleted in commit 8978b3bb. Verified by uv run pytest -q packages/congress_api/tests/test_body_store_contract.py.
