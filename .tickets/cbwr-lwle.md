---
id: cbwr-lwle
status: in_progress
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

