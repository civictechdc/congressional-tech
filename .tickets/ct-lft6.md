---
id: ct-lft6
status: open
deps: []
links: [ct-gi01]
created: 2026-11-08T17:33:29Z
type: task
priority: 3
assignee: mikewolfd
tags: [capture, ct-gi01]
---
# Finish the paid recapture of 564 legacy Explorer files

Split from ct-gi01 (owner decision 2026-11-08). Owner-approved paid Zyte/Firecrawl retry of 445 out-of-scope legacy URLs plus 119 free-run failures, no cost cap. Selections, scripts and per-round evidence: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-gi01/20261108-claude/recapture-plan/ (cl-paid-loop.py). Firecrawl returned HTTP 500 on every call on 2026-11-08, so later rounds run Zyte-only; each round stops at the first uncertain provider result. Done when every URL has an outcome, the counts are recorded, and new receipts are picked up by the next capture append.


## Notes

**2026-11-08T17:43:24Z**

2026-11-08: all 564 URLs have an outcome after 237 rounds (883 requests, $6.14 reserved at conservative bounds; Firecrawl returned 500 on every call, so most rounds ran Zyte-only). Stored 56 new bodies, 21 unchanged (77 covered: congress.gov 38, YouTube 37, judiciary.senate.gov 2); 278 request_failed, 194 failed (404/410/403), 3 retry_later, 12 without an outcome line. Receipts are in congressional-tech-raw. Remaining: the next capture append/nightly ingests them.

**2026-11-11T14:40:15Z**

validated 2026-11-11, left open: the remaining step cannot happen as the ticket expects. The paid and free retry runs wrote their cutoff receipts under receipts/owner/gi01-legacy-retry-20261108/ (356 receipt keys in the run summaries of implementation/post-release-ticket-finish-20261107/owners/ct-gi01/20261108-claude/recapture-plan/), and that family is not in model/jobs/publish-daily.json receipt_families (22 families; no owner/*), so the nightly never discovers them. Measured on the live release 77673bfb8fcf's archive-model/evidence/capture_evidence.parquet: 0 of those 356 receipt keys and 0 of the 54 bodies they stored (outcome stored, from each attempt's committed.json) are present, while the same runs' documents/ (18 of 18 bodies, 114 of 114 receipt keys) and govinfo/ (22 of 22 bodies) receipts are. Remains: an owner decision to admit receipts/owner/gi01-legacy-retry-20261108 (add the family to the daily, or import those receipts once through the backfill), then a release showing the 54 bodies.
