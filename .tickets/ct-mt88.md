---
id: ct-mt88
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [daily, capture, discovery]
---
# Receipt discovery cannot see a late receipt in an older day prefix

From the 2026-11-10 cause review: discovery lists only each family's newest day onward and never `undated`, so a receipt written late into an older prefix is invisible (stated by the reviewer, to verify in code first). Separately the nightly's own receipt lists missed 44 receipts that the attempts comparison exposed, and the daily budget (oldest receipts first, daily.py _within_budget) left a tail of 4,339 receipts dated 10-31 out of the 11-04 build, ingested three hours after the 11-08 release published. The last is by design; say so in docs so a later reader does not call it a fault. Source: .cache/archive-release/release-20261110/causes/capture-address/README.md, .cache/archive-release/release-20261110/causes/review-capture-address/.

## Acceptance Criteria

The blind spot is confirmed or refuted from code with a test; if real, discovery finds a planted late receipt in an older prefix; the 44 missed receipts are explained.


## Notes

**2026-11-11T14:40:09Z**

validated 2026-11-11, left open; the blind spot is confirmed from code, no test yet. receipt_inventory.discover_receipts (lake/receipt_inventory.py:67-116) in incremental mode keeps a prefix only when it is a date and cast(day) >= that family's newest existing day; undated prefixes and older days are listed only in backfill or raw-check mode. So a receipt written late into an older day prefix is not discovered by the nightly. Remains: the planted-late-receipt test and a fix (or a periodic backfill-mode listing), the docs note that the oldest-first daily budget tail is by design, and the 44 missed receipts explained.
