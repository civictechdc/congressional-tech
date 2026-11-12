---
id: ct-lft6
status: closed
deps: []
links: [ct-gi01, cat2-ddas, ct-17op, cat2-x47u, ct-jcnd, ct-esuu, ct-5q3g]
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

**2026-11-12T03:22:52Z**

Executed Option C from investigations/lft6-recapture-import-20261111/NOTES.md (live direct re-fetch into declared documents family, avoiding false 'recovered' labels and excluding the 37 YouTube watch pages and 11 HTML error pages that produce 0 documents; the 12 'no_line' URLs in paid-urls-v2.json are internal/retired/malformed host refusals: 3 docsadmin-clerk.house.gov, 4 edit-*.rules.house.gov, 3 thomas.loc.gov, 1 www.rules.house.gov, 1 garbled URL). Run 20261112T030230Z-be9f629dc95f (writer commit 882a5451886463e16f8dfbce2a26f89a7d938776, evidence investigations/lft6-recapture-import-20261111/live-refetch-20261112/work/) fetched all 27/27 congress.gov PDFs (17 stored + 10 unchanged in lf_bodies_75.csv) at HTTP 200 (218,452,747 bytes, $0 provider spend, outcome=unchanged matching existing raw bodies) and wrote 27 receipts under receipts/documents/2026-11-12/. Close once the bundle release ingests them and records the published document count.

**2026-11-12T06:30:22Z**

Published in release `ede659a056c04ce0c4f51c70b6848b4eaf1db1a2a2fa8aee04076973e2a1a450` (`nightly/20261112T061147.068599Z`, commit `ea76829fa376980a038cfcc1faa16b9901223cf7`, cause record `model/jobs/release-causes/21fc049940bb-ede659a056c0.json`, notes `docs/releases/2026-11-12-ede659a056c0.md`). Verified on the published Parquet tables against `21fc049940bb`: all 27/27 `congress.gov` PDF receipts (`receipts/documents/2026-11-12/20261112T030230Z-be9f629dc95f-*`) ingested into `readings_compact_20261112` (snapshot `6062423150257890726`) and `captures` (snapshot `9129815301243027813`), producing +21 new `congress.gov` PDF documents (`+22` link keys including 1 PDF rendition body key on `BILLS-116HR2203-RCP116-27`, where `.pdf` leads and `.xml` remains in `alternates`) and joining 6 existing documents as copies (`+27` `sources.parquet` rows, `+27` `urls.parquet` lookup rows, 4 House documents gaining `chambers=['house']`, `committee_keys`, `meeting_keys`, and `document_date`, 3 gaining `witness_keys` and `congress`, and +25 document coverage counts across 21 House meetings). Closed.
