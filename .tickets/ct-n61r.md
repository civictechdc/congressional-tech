---
id: ct-n61r
status: open
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
