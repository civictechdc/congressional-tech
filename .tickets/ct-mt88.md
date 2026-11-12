---
id: ct-mt88
status: closed
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

**2026-11-12T04:33:00Z**

Resolved and closed:
1. **Planted-late-receipt `Red -> Green` tests & bounded lookback fix (`INCREMENTAL_LOOKBACK_DAYS = 14`):**
   - `packages/congress_api/src/congress_api/lake/receipt_inventory.py` (`discover_receipts`): incremental mode now lists each family's dated prefixes from `w.newest - INTERVAL '{lookback_days} days'` onward (`INCREMENTAL_LOOKBACK_DAYS = 14` by default, shared identically by `daily.py` and `archive_publish_job._require_current_daily`). A receipt written late into a recent prior day prefix (for example across UTC midnight, or behind a supervised single-receipt ingest while `_within_budget` still had deferred receipts on an earlier day) is discovered and ingested without listing full bucket history; `backfill`/`raw-check` continue to list full history and historical non-date segments (`undated`).
   - Verified `Red -> Green` by `test_incremental_discovery_finds_planted_late_receipt_in_older_day_prefix_within_lookback` (`test_receipt_inventory.py`) and `test_daily_discovers_late_receipt_planted_in_older_day_prefix` (`test_daily_receipt_discovery.py`).
2. **Docs note on oldest-first `(day, key)` daily budget tail:**
   - Documented in `docs/releases/README.md` (`Nightly publication`) that `daily.py` (`_within_budget`) keeps a prefix of selected receipts in `(day, key)` order up to `max_work_items` and therefore drains families within a single day alphabetically (`receipts/<family>/...`), so a deferred alphabetical family tail (`govinfo/*`, `house/*`, `senate/*` — the 4,339 `2026-10-31` receipts ingested after `630164505301`) is by design.
3. **Forensic explanation of the 44 receipts in `cb_02_new_receipts_and_attempts.json`:**
   - Those 44 receipts (`43` `congress/meetings/2026-11-08/20261108T190655Z-99156488897a-000001..000043.jsonl.gz` from `b14-meeting-fetchers` `ct-q4e2`, retrieved `19:06:55Z–19:07:33Z`, plus `1` `documents/2026-11-08/recovery-campaign-4bec5789...jsonl.gz` from `recovery-campaign` `ct-umtm`, imported `19:01:29Z`) **were discovered by `discover_receipts`**, not missed by discovery: `.cache/archive-release/nightly/20261108T235910.088764Z/previous-candidate/archive-daily/receipt-discovery/selection/result.json` records `count = 44` for those exact 44 keys.
   - That `20261108T235910.088764Z` nightly run appended those 44 receipts to `captures` and `readings` and then failed before writing `daily-summary.json` (triggering `producer_unrecorded` in `20261109T002515.405117Z` before owed-record recovery settled the heads). Because `cb_02_receipts.py` assembled its initial list (`5,806` keys) solely from `daily-summary.json` `new_receipt_keys` across `20261108T181325Z` (`5,782`), `20261109T224443Z` (`12`), and `20261110T011925Z` (`12`), it omitted `20261108T235910Z` (which lacked `daily-summary.json`); `5,782 + 44 + 12 + 12 = 5,850` accounts for 100% of the candidate's new receipts (`30,192 - 24,342 = 5,850`).
