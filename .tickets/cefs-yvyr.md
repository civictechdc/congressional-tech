---
id: cefs-yvyr
status: in_progress
deps: []
links: []
created: 2026-10-27T14:13:27Z
type: task
priority: 2
assignee: mikewolfd
parent: cef-6q2y
tags: [engine-first, site]
---
# A3-A4-A11: candidate canary and measured browser thresholds

## Acceptance Criteria

One shared reader verifies a pinned candidate in under one minute; browser contract loads the real built site; measured target writer requires real phone and desktop samples including worker heap. Real-device execution remains owner-gated.


## Notes

**2026-10-27T16:02:18Z**

Implementation and local final F0 validation are complete: the canary passed in 10.617 seconds with an actual stored body; desktop, phone-profile and 404 browser checks pass. The target writer rejects profile-only receipts; both consumers use archive-targets.json. Blocked: owner real-phone/desktop measurements, accepted time/heap ceilings, and the actual uploaded HTTPS candidate check. Exact commands are in docs/measurements/engine-first-20261027/site/README.md. No real-device qualification is claimed.
