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

