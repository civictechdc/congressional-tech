---
id: ct-n61r
status: closed
deps: []
links: [ct-r4rd, ct-gi01]
created: 2026-11-02T04:01:45Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [model, meetings, phase2]
---
# not_held=false on 407 Canceled or Postponed meetings

review-c-explorer: the not_held rule is a title regex only, so 407 Canceled or Postponed meetings show not_held=false.

## Acceptance Criteria

Use publisher status, checked against raw.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Cause: the House parser never read the House meeting status; raw XML puts it elsewhere (since 9e656389). Publisher status changes 412 meetings (the 407 plus 5 reversed). impl-f, r1b-f.

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): impl-f: 10 commits on r1b-f. Frozen before/after and raw check: access 7/7, not_held 409/409, House witness lists 187/187; the 3 same-day status conflicts resolved as held, from a registry. The path arm waits on e1's captures.original_path.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): current-status misread since 9e656389; not_held +404/-5, 409 supported by raw. The 3 same-day conflicts (110924, 116426, 116998) each have their own YouTube video named for the meeting, streamed live on its date; they keep publisher status with not_held=false via model/registries/meeting-status-conflicts.json, evidence quoted.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): red-f: 101498, 101400, 104460 and 101644 are Canceled on Congress.gov but held per their own print; derive held generically from the meeting's own print and keep the publisher status as a conflict. Sent to impl-f.

**2026-11-02T15:10:29Z**

2026-11-02 red-f2 (BLOCK, narrow): 116426 never sat (held Dec 5 as 116584) and 116998 was re-noticed as 117059, so both registry rows come out; the print override marks 9 superseded duplicates as held (e.g. 105066, replaced by 105084).

**2026-11-02T16:11:20Z**

2026-11-02 impl-f: registry rows for 116426 and 116998 removed; 105066 is not-held again (a canceled same-day duplicate gives way to the meeting that sat).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
