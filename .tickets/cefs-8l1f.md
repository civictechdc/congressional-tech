---
id: cefs-8l1f
status: in_progress
deps: []
links: []
created: 2026-10-28T16:55:13Z
type: task
priority: 2
assignee: mikewolfd
---
# Prepare G13 filename export removal

Lead-delegated filename_exports and its dead tests only; preserve raw/committee/parked consumers and shared compaction APIs. Replacement archive release registry/files. No merge.


## Notes

**2026-10-28T17:08:14Z**

G13 filename_exports removal only; retained compact_readings and compact_reviews plus all remaining tests. Focused archive/seed/compaction tests 31 pass in 18.32s; resumed interrupted Node check 82 pass, Astro 29 pages in 1.89s. No production imports remain for filename_exports or deleted publisher paths. Full lane and root review follow; no merge.
