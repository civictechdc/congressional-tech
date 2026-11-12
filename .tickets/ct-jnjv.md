---
id: ct-jnjv
status: closed
deps: []
links: [ct-0hay, ct-m878, ct-m704, ct-chc4]
created: 2026-11-09T23:14:53Z
type: task
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, r2]
---
# Pin MD5-less body reads from one bucket listing, not a one-byte GET per body

body_text reads a remote body that has no captured MD5 by first asking the origin for one byte and pinning the full read to the ETag it answers (`body_text._observed_etag`, branch claude/ct-thread4-slice 7a3701fd on local main (was b945aedc before the rebase); the owner chose "one-byte check now, listing later" on 2026-11-09). That is two requests per such body. A bucket LIST returns key, size and ETag for 1,000 objects per request, so one listing pass (a `body_listing` input with the same copy-selection SQL the plan already uses) would pin every read with no probe: O(objects/1000) requests in place of O(MD5-less bodies) extra GETs.

Do this before or alongside the full-corpus run only if the measured probe cost matters; the slice ran with it and finished. Share the copy-selection SQL between the plan and the listing join instead of adding a second copy.

## Acceptance Criteria

- MD5-less remote reads are pinned by size and listed ETag with no per-body probe request.
- The refusal cases the probe covers today still refuse: weak ETag, changed size, an origin that ignores Range (test_body_text_origin.py::test_an_md5_less_read_refuses_an_origin_answer_it_cannot_pin keeps passing or is replaced by an equal listing case).
- Request count per MD5-less body measured before and after on the slice.


## Notes

**2026-11-10T03:56:09Z**

2026-11-10 measurement: 60 random bodies from the captures pin, one-byte Range GET against the public origin with a fresh connection each (urllib, User-Agent ct-body-text/1): median 293 ms, p90 430 ms; 57 of 60 answered 206 with the captured size (the other 3 not examined). The producer reuses a client connection, so its real cost per probe is lower and unmeasured. Upper bound for the full run at 12 workers: 584,000 bodies x 0.3 s / 12 = about 4 hours of a multi-day run, and for cheap html bodies the probe is a large share of per-body time. A bucket LIST would replace this with about 600 requests but needs R2 credentials: the public origin does not list, so the local full run (body-text-full-20261110) cannot use it. Scope of this ticket is therefore the credentialed production route only. Cheaper first step if wanted: time the probe inside the worker (one counter) on the running job before building anything.

**2026-11-11T14:40:09Z**

validated 2026-11-11, left open: not done. lake/body_text.py:236 still pins an MD5-less remote read with _observed_etag (line 246), the one-byte probe; no listing input exists for body_text. Scope stays the credentialed production route.

**2026-11-12T04:30:00Z**

Closed on `claude/ct-wave-6-bodytext-prep`:
- Added `body_listing` input + module-level `LISTING_SCHEMA` to `lake/body_text.py` (`plan()`, `run()`, streaming atomic `write_body_listing()` over `list_objects_v2` via `ParquetWriter` + `os.replace`) and wired `--write-body-listing` (`--raw-bucket`, `--listing-prefix`), `spec['write_body_listing']`, and `spec['body_listing']` in `cli/body_text.py`.
- Shared `copy_selection_steps(with_listing=...)` joins `body_listing` before copy ranking (`ORDER BY copy_usable DESC, stored_bytes IS NULL, ...`, aligned with `lake/readings.py`) so a listed `.gz` fallback copy wins over an unlisted `''` copy, `stored_bytes IS NULL` remains `missing_pins`, and `work-list.parquet` is placed atomically only after `conflicts` and `listing_conflicts` pass.
- When `body_listing` is supplied, MD5-less remote reads pin directly by `stored_bytes` and listed strong `ETag` with **zero** `bytes=0-0` probe GETs (`_observed_etag` is never called; kept intact when `body_listing` is omitted on the uncredentialed public-origin route).
- All refusal cases preserved and tested in `test_body_text_producer.py` and `test_body_text_origin.py`: weak ETag (`W/...`), listed `size != stored_bytes`, missing key in listing, listed `.gz` fallback over unlisted `''`, sizeless capture (`stored_bytes IS NULL`), listed ETag conflicting with captured MD5, duplicate/invalid listing rows (leaving no `work-list.parquet`), origin ignoring `Range` (`200` on ranged read), and `If-Match` `412` when an object changes after listing.
- Request-count measurements (`.cache/archive-release/investigations/wave6-bodytext-prep-20261112/ct_jnjv_request_counts.json`):
  - **1/16 Slice (`37,616` MD5-less + `133` MD5-pinned fetched; `65,958` bucket objects in prefix `0`):** Before = `75,365` requests (`37,616` probes + `37,749` GETs = **`2.0`** reqs/MD5-less body); After = `37,815` requests (`0` probes + `37,749` GETs + `66` LISTs = **`1.0` GET** / **`1.001755` total** reqs/MD5-less body; **`37,550` requests saved**).
  - **Full Corpus (`605,564` MD5-less + `1,864` MD5-pinned fetched; `1,056,494` bucket objects):** Before = `1,212,992` requests (**`2.0`** reqs/MD5-less body); After = `608,485` requests (`0` probes + `607,428` GETs + `1,057` LISTs = **`1.0` GET** / **`1.001745` total** reqs/MD5-less body; **`604,507` requests saved**).
  - **Empirical 30-body Loopback (`25` MD5-less + `5` MD5-pinned):** `50` GETs (`2.0`/MD5-less body) before vs `25` GETs + `0` probes + `1` LIST (`1.0` GET, `1.04` total/MD5-less body) after.
