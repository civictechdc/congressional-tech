---
id: ct-fd16
status: closed
deps: []
links: [ct-itcg]
created: 2026-11-04T02:29:12Z
type: feature
priority: 2
assignee: mikewolfd
tags: [engine, lake, basin]
---

# Restore the canonical archive tables with a verified snapshot replacement

Closed as deferred on November 5, not as implemented. Current jobs and readers use the verified `archive_r1b.*` generations. The earlier stale writer/reader binding was repaired under `ct-itcg`; no current consumer has been identified that requires `archive.*` names or same-table snapshot history.

Reopen when a named consumer or approved migration needs that identity. Establish whether it needs only a stable name or the same table identity and history before choosing an engine change. The pinned native job path still lacks whole-snapshot replacement; empty-table import and append-only merge do not replace corrected rows in an existing head.

## Deferred acceptance criteria

- DocSpec can commit the contents of a pinned source as the next native table snapshot. Compare the complete row multiset both ways with `EXCEPT ALL`, handle schema differences explicitly, and retain earlier snapshots for rollback.
- Advance `archive.*` to the then-current `archive_r1b.*` snapshots. Switch the five job specs and `publish-model.json` together and show the existing release comparison check passes against the live release.

At reopening, inventory the actual active bindings and producer records rather than treating the historical file count as complete. Bind the operation to the expected source and target heads, preserve the old snapshot, and qualify changed, inserted and deleted keys plus schema and concurrent-head conflicts before a coordinated switch. Keep the corrected live generations selected until that work is accepted.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-05T20:18:16Z**

Closed as deferred, not delivered: no named current consumer needs canonical table names or same-table history. Preserve replacement, multiset, schema and rollback criteria for a concrete reopening trigger; keep ct-itcg closed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).
