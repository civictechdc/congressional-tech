---
id: ct-k7rw
status: open
deps: [ct-medh]
links: []
created: 2026-11-17T18:51:21Z
type: task
priority: 3
assignee: mikewolfd
tags: [hosted, gate5, performance]
---
# The producer-record chain walk reads one stored record per past night, per table, every night

Found reviewing ct-medh (2026-11-17). `producer_records.base_problems` walks a table's records back to its root (an import, a backfill or a capture stage): one R2 read and two git calls per link. Each night's daily append adds one link per table, so the walk is O(nights since the root) per table per night, and the total over time grows with the square of the nights. With ct-medh the walk runs twice a night (the daily's pre-check, then gate 5). `ProducerRecords` caches nothing.

Today: a handful of links per table, a few seconds. After a year without a backfill: about 9 tables x 365 links x 2 walks, roughly 6,500 reads a night.

## Design

Records are write-once, so a found record can be kept for the life of the process (never cache "absent": records are written during the run). That makes the second walk free. To stop the growth itself, the walk needs a verified stopping point that advances, for example the head the last published release's gate 5 accepted.

## Acceptance Criteria

Gate 5 and the pre-check together read each record at most once per run, and the number of records read per night does not grow with the number of past nights. Measured on the production chain before and after.
