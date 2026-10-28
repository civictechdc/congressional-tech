---
id: cbwr-lwle
status: closed
deps: []
links: []
created: 2026-10-28T02:34:39Z
type: bug
priority: 0
assignee: mikewolfd
---
# Make rescued snapshot import safely resumable and rehearse two snapshots

## Acceptance Criteria

Actual rescue CLI succeeds twice against a local fake store with unchanged object bytes and counts, refuses conflicting receipts and stale import dates, and preserves the input batch


## Notes

**2026-10-28T02:57:44Z**

Actual CLI ran twice on copies of two real snapshots (122 files, 303593622 bytes), preserving input and stored identities. Conflict and stale-date guards pass; before/after-ack multi-receipt interruption tests also pass. Live import remains an owner action with exact command and same-day retry limits.
