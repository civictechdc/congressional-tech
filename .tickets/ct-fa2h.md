---
id: ct-fa2h
status: closed
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [capture, senate, url_state]
---
# www.energy.senate.gov refuses the fetcher: 303 in-scope addresses at 403

url_state on 2026-11-10: 303 in-scope www.energy.senate.gov addresses are at 403, including 9 that were 200 and stored on 2026-10-05 (e.g. .../hearings-2025-12-17-business-meeting-to-consider-pending-legislation/). 506 of the 510 first fetches reported earlier are /wp-json/oembed/ addresses the scope already excludes. Separately 88 Senate addresses went from 404 to a request failure with no status. No address lost last_good_at. Source: .cache/archive-release/release-20261110/causes/review-capture-address/.

## Acceptance Criteria

The 303 addresses are fetched, or the refusal is recorded with what was tried (user agent, rate, route); the 88 request failures have a recorded status or reason.


## Notes

**2026-11-11T14:40:09Z**

validated 2026-11-11, left open: unchanged in the live release. DuckDB on 77673bfb8fcf url_state.parquet, www.energy.senate.gov excluding /wp-json/oembed/: 1,426 at 200, 303 at 403 (last attempt 2026-10-30), 69 at 404, 8 with no status. Nothing has been tried since the filing.

**2026-11-12T03:22:52Z**

Fixed in packages/source-fetch and recaptured live on 2026-11-12 (run 20261112T031832Z-f7ede707000a, writer commit 882a5451886463e16f8dfbce2a26f89a7d938776, evidence .cache/archive-release/investigations/fa2h-recapture-20261112/).

Root cause from raw receipt 20261031T001950Z-39c3fc2e7833-000013.jsonl.gz (body af8db01b...): Akamai EdgeSuite $(SERVE_403) rejected direct requests carrying only Accept-Encoding + the truncated Python User-Agent 'Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36' without browser navigation headers. Updated source-fetch direct transport to send desktop navigation headers (User-Agent 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', Accept, Accept-Language, Upgrade-Insecure-Requests, Sec-Fetch-Dest/Mode/Site/User) while preserving caller overrides and leaving Zyte API calls untouched.

Live recapture results across all 391 target URLs (3 files/s, 3 workers, direct-first with Zyte fallback configured; $0.00 Zyte spend, 407 receipts written to senate/pages and documents):
- 303 www.energy.senate.gov 403 URLs (excluding /wp-json/oembed/): 302 fetched HTTP 200 (outcome=stored, direct) and 1 returned HTTP 404 (outcome=failed: .../hearings-2022-7-full-committee-hearing-to-consider-pending-legislation/S.%204038); 0 remain at 403. Plus 16 newly discovered www.energy.senate.gov URLs fetched HTTP 200 (stored).
- 88 Senate 404 -> request_failed URLs: all 88 recorded with status or reason — 54 returned HTTP 404 (outcome=failed: www.help.senate.gov 38, www.agriculture.senate.gov 7, www.energy.senate.gov 6, www.judiciary.senate.gov 2, www.commerce.senate.gov 1) and 34 recorded outcome=request_failed with reason=excluded_redirect (CMS 302 to out-of-scope path on www.judiciary.senate.gov 25, www.armed-services.senate.gov 5, www.hsgac.senate.gov 4).
