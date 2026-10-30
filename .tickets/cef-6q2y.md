---
id: cef-6q2y
status: closed
deps: []
links: []
created: 2026-10-27T13:40:54Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine-first, reader]
---
# A: shared release reader, canary and site presentation

## Acceptance Criteria

Native F0 and hand fixtures decode through one DOM-free reader; indexed detail and link reads, saved copies, dates, recoveries, sources, filters and stale tabs pass the project runner. Real-device speed targets remain owner-gated.


## Notes

**2026-10-27T16:02:18Z**

The reader handoff is complete and independently reviewed. Corrected final F0 release 62bddc63 loads locally in desktop and phone profiles; the canary passed in 10.617 seconds. Full production-offline at 9eb923c2: 11,382 passed, 33 failed and 3 errors; all 36 baseline identities are unchanged. All15 canonical recovery labels preserve their claims. UI/label tickets are closed; this parent and the harness retain real-device target and publish/CI owner gates. No live writes or deployment.

**2026-10-30T14:32:56Z**

Completed and verified against live Phase-2 release 2026-10-30-a95e8b21; remaining Phase-2 explorer UI work tracked under master epic ct-77zb.
