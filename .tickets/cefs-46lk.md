---
id: cefs-46lk
status: closed
deps: []
links: []
created: 2026-10-27T14:13:27Z
type: task
priority: 2
assignee: mikewolfd
parent: cef-6q2y
tags: [engine-first, site]
---
# A5-A10: release document pages with saved copies and source context

## Acceptance Criteria

The built archive page passes desktop and phone-profile browser contracts for saved copies, dates, recoveries, sources, hearing keys, versions and hidden direct-link notices against the native hand release and final F0.


## Notes

**2026-10-27T16:02:18Z**

Validated locally against corrected final F0 release 62bddc63 and native hand release 00981fd5. Desktop 1440×1000 and phone 390×844 browser contracts pass, including 404 reload, Back cancellation, sources, dates, recoveries, versions and review notices. Full regression at 9eb923c2: 11,382 passed, with the same 36 baseline failure identities and no new failures. The 10 unit and 4 rendering checks cover all 15 canonical kinds. Sandbox and page-owned worker heap checks pass. No live deployment.
