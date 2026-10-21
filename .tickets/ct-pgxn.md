---
id: ct-pgxn
status: open
deps: []
links: [ct-nloa, ct-xu1o, ct-ur2y, ct-qkvr]
created: 2026-10-21T15:27:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [news_lake, docspec, scale, measurement]
---
# Measure per-table native news poll cost against archive size

docspec-rs replace_keys prunes retained files only by exact per-file key bounds (src/engine/write/key_points.rs). news_lake keys most tables with deterministic uuid5 hashes (context.py named_id: items, versions, mentions, discoveries, classifications, identity_decisions, runs, stories, story_members, entities, outlets). Only captures use time-ordered UUIDv7 (ct-ur2y). Hashed keys spread across the whole key space, so a key-scoped Update on those tables is expected to key-decode every retained file each poll. No per-table measurement exists yet. This ticket decides whether the upsert tables need bloom filters (spicy-stack ss-wie5) or whether time-keyed appends (linked ticket) are enough.

## Design

Reuse the existing native backend and WriteMetrics (files_scanned, files_reused, bytes_reused, bytes_written) from each table's processing phase; add no new counters. Run one fixed poll (same items, versions and mentions) against retained archives of 1x and 10x unrelated polls. Record bytes read, files scanned, wall time and peak RSS per table. Local fixture numbers are not production throughput; label them as such.

## Acceptance Criteria

- Table of per-table files_scanned, bytes read, wall time and peak RSS for the fixed poll at 1x and 10x retained archives, before any key or bloom change.
- Identify which tables scale with archive size rather than poll size and rank them by cost.
- State a decision: whether ss-wie5 (bloom filters for items/entities upserts) is needed, with the measured numbers.
- Retain the receipt under output/ and link it here.

## Realistic scale (required, added 2026-10-21)

Fixture-sized runs (a few files, tens of rows) prove correctness only; they are not evidence of cost. Qualify at these tiers, stated as assumptions until the pilot measures real volume (docs/packet.md I5: "scale according to measured gaps"):

| Tier | Polls (hourly) | Items/poll | Versions/poll | Mentions/poll | Retained files/table (no compaction) |
|---|---|---|---|---|---|
| T1 pilot month | 720 | 2,000 | 2,000 | 10,000 | ~720 |
| T2 one year | 8,760 | 2,000 | 2,000 | 10,000 | ~8,760 |

- Keys match production shape: uuid5 over the real name templates (context.named_id), not sequential integers.
- Measure at T1 plus at least one larger point toward T2 (for example 2,160 polls = 90 days), and report whether cost per poll is flat or grows with retained size. Extrapolate to T2 from at least two measured points; never from one.
- Record wall time per poll, files_scanned, bytes read, peak RSS, lifecycle metadata bytes and disk used. Use a release build.
- Local constraint: about 55 GiB of free disk. Bodies may be truncated to a fixed realistic length (C5 metadata_only records are valid); state the truncation and that key-probe cost depends on key columns and file count, not body size.

## Notes

**2026-10-21T15:30:06Z**

2026-10-21: started realistic-scale measurement with release harness docspec-rs examples/news_poll_scale.rs (uncommitted). It simulates the news.versions append path: hourly polls of 2,000 rows with uuid5-shaped keys, 200-byte bodies (truncated, stated), lifecycle compacted every 24 polls. Two variants: keys ['id'] (today) and ['observed_at','id'] (ct-xu1o). Target: T1 = 720 polls, then a second point toward T2. Results will follow in notes here.

**2026-10-21T15:55:59Z**

Validation against engine source (docspec-rs 270a8b6): the retained-files columns (~720 T1 / ~8,760 T2, no compaction) likely overstate file count. The native rolling writer coalesces appends toward a target file size with buffers surviving individual writes (storage.rs:338-342, RollingFileWriterBuilder at :396). The real cost driver is key-range overlap: uuid5 keys give every retained file a near-total key range, so every retained file is key-decoded per poll whatever the count. files_scanned stays the deciding metric. Add per-table file-size distribution (avg/p50) to the receipt alongside files_scanned/bytes/RSS so the bloom (ss-wie5) vs time-key (ct-xu1o) decision can distinguish many-tiny-files from few-large-files-still-all-scanned.
