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
