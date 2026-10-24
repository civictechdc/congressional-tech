---
id: ct-upl1
status: closed
deps: []
links: []
created: 2026-10-20T16:51:06Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, storage, recovery]
---
# Make news_lake upserts atomic and monotonic across crashes and late arrivals

storage/coordinator.py:181-208 performs upserts on news.outlets, news.items, and news.entities as two separate Iceberg commits (table.delete followed by table.append) while reading prior state from table.current_snapshot(). A crash between delete and append leaves the row absent in current_snapshot(), so recover() sees prior=None and appends the unmerged incoming record from the journal, permanently erasing prior merged evidence (first_seen_at, url_aliases, domains, feed_urls, aliases, identifiers, tenures). In addition, _merge_upsert (storage/coordinator.py:57-81) unconditionally overwrites scalar fields (recorded_at, name, current_version_id, content_type) even when the incoming record has an older recorded_at than prior.

## Design

1. Commit upsert replacements atomically (e.g., via a single PyIceberg transaction combining delete and append, or by resolving prior against the baseline release snapshot) and add an explicit fault-injection point for upsert replacement so crash recovery is tested across upsert mutations.
2. In _merge_upsert, compare parse_instant(record['recorded_at']) against parse_instant(prior['recorded_at']): always union list-valued evidence fields and keep min(first_seen_at), but only allow scalar fields to overwrite prior when the incoming record is at least as recent as prior.

## Acceptance Criteria

- Injecting a crash at every step of an upsert cycle (when second_batch updates existing outlet, item, and entity IDs from batch) preserves all prior list evidence and earliest first_seen_at after recover().
- Committing a late-arriving older poll after a newer poll preserves new scalar values (recorded_at, name, current_version_id) while still unioning any new alias/domain/identifier evidence from the late poll.
- Update conftest.py / test_recovery.py and test_coordinator_replay.py with regression tests covering mid-upsert crashes and out-of-order poll merges.


## Notes

**2026-10-20T17:30:45Z**

Implemented atomic upsert delete+append in one Iceberg transaction, upsert_replace fault points, and monotonic scalar/list merging. Recovery tests cover all upsert crash points with overlapping IDs plus late older polls. Full suite: 281 passed.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch kl2a1aa).
- Grades: proposal 90 → 90, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
