---
id: ct-jnjv
status: open
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
