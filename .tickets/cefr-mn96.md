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

**2026-10-28T03:34:02Z**

Measured proof ingress, conflicts, binary types, ordering and CAS covered by contract-first0f50a23f/58230b33; exact restore/apply guard preserved. Reviewed forward custody fix dc854def;40focused PASS13.31s and final combined104PASS19.25s on9b59263. Repair/restore application owner-gated with exact README commands; no real repair ran.

**2026-10-28T12:07:30Z**

Owner mixed-join global rule follow-up: use all null-safe repair identity hash keys, explicitly filter the formerly ordinary-equality body key on the matching side, and preserve NULL-key refusal/unmatched accounting. New physical-plan fixture and existing exact repair/locator evidence checks; no live repair.

**2026-10-28T12:09:45Z**

Mixed-join correction contracta52eb5b7 reproduced1 physical-plan failure/1 NULL-body preservation pass. Final repair/locator/evidence group32PASS11.65s on sharedb2. All four identities are null-safe hash keys; matching-side body-key filters preserve NULL nonmatching semantics, including unmatched=1/ambiguous=0 for NULL candidates. No live repair; combined CODE review pending.
