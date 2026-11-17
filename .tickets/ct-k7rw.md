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

Done 2026-11-17 (pull request 195): one store keeps the bytes of a record it has found, so the pre-check and gate 5 together read each record once per run, not twice.

Still open: the walk reads one record per past night. Preferred design (owner question, 2026-11-17: "why stop early vs trust the pins and only read when needed?"): trust the pins.

Since ct-medh the nightly checks a head before it appends onto it (`daily._producer_bases`), then writes that head record's hash into its own record as `base.record` (`daily.py`, the `base=dict(selector=..., record=chain['bases'][name])` line). So a nightly record's pin on its base is the receipt for a check that already ran. The walk re-derives, every night, what each night's writer already checked.

Trust the pins: judge the head record in full (format, registered job, reachable commit, job checked in there, versions, its append-only link) and accept its `base.record` pin without reading further, when the head record was written by a job that runs the base check before appending. One record read per moved table per night, nothing new stored, no change to the published release's input record.

What this relies on, to verify before building:
1. Every path that writes a producer record runs the base check first. All six call sites in `lake/daily.py` go through `_producer_bases`; the backfill and import jobs have not been checked.
2. The starting state is sound: release eb6710bb1a14 (2026-11-17) passed gate 5 with a full walk, so every chain up to its heads is verified.
3. A record that names no base (a capture stage, a backfill) stays a root judged on its own claims, as today.

What it cannot see, compared with the full walk: a later rule change is not re-applied to old records, and a rewrite of main's history that orphans an old producing commit goes unnoticed. Keep the full walk as a function and run it in the weekly maintenance job and on demand.

Considered and set aside: stop at the snapshot the live release was built from. It reads the same one record on a normal night but needs the nine snapshot pins stored with each published release and kept out of the data-only night's same-inputs comparison. More state, same result.

## Acceptance Criteria

Gate 5 and the pre-check together read each record at most once per run, and the number of records read per night does not grow with the number of past nights. Measured on the production chain before and after.

## Notes

**2026-11-17**

Part one merged as pull request 195 (22db4500). Owner, 2026-11-17, on building the trust-the-pins design above: "Yes, after the night", meaning after the scheduled night of 2026-11-18 passes. Own pull request; first verify that the backfill and import jobs run the base check before they write a record.
