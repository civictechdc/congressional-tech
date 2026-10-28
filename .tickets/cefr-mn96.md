---
id: cefr-mn96
status: in_progress
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

**2026-10-28T02:02:34Z**

Retro-review requires actual measured stored SHA/size matching receipt assertion before repair eligibility. Contradictions retained and unmeasured candidates never become repairs; no added GETs beyond existing sample/orphans. Shared narrow native proof predicate before grouping preserves binary/order/count/CAS/source-pin guards.38 focused passed13.23s with48636e5; no real repairs/network writes. Await mandatory CODE/ARCH review before close.
