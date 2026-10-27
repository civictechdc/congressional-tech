---
id: cefr-mn96
status: closed
deps: []
links: []
created: 2026-10-27T14:08:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B12: stage explicit old-index repairs and verify daily digest facts

## Acceptance Criteria

Report missing indexed bodies and exact stored-byte digest discrepancies; local repair plans preserve all other facts and reject stale pins; live repairs owner-gated.


## Notes

**2026-10-27T15:38:48Z**

Local done: exact-evidence repairs preserve ordinal/schema/old versions/counts and CAS source pin; missing-body restoration verifies exact stored bytes. CODE findings fixed0c9a252e; independent fix review APPROVE;17 native/local cases and20 command/ratchet checks pass. Actual repairs, live daily confirmation and inputs remain owner-gated with exact commands.
