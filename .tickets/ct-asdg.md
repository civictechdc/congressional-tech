---
id: ct-asdg
status: open
deps: []
links: [ct-r4rd, ct-gi01]
created: 2026-11-02T04:01:45Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [model, meetings, phase2]
---
# False rescheduled_to: Rescheduled does not mean moved

review-c-explorer: 791 of 956 Rescheduled meetings have their own video or transcript. 106383 (own video, Part I to Part II) and 112524 (own transcript, witnesses) are wrong. Cause: old.stated ignores own evidence, and title_key merges parts.

## Acceptance Criteria

entity-meetings.sql is fixed before publishing, checked against raw per row.

