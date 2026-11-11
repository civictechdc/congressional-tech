---
id: ct-uul8
status: open
deps: []
links: []
created: 2026-11-10T13:36:28Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, meetings]
---
# Printed hearings attached to the wrong meeting or to none: 3 on a Senate business meeting, 8 with no meeting

Found 2026-11-10 while reading the 343 name clashes (.cache/archive-release/investigations/name-clash-review-20261110/README.md, 'Off topic but found'). Three GovInfo printed hearings are attached to a Senate business meeting instead of the hearing they print (documents 130655, 138297, 138459), and eight printed hearings have no meeting at all (listed there). Not verified beyond the reader's note.

## Acceptance Criteria

Each of the eleven is attached to its hearing, or the reason it cannot be is recorded; the rule that attached the three is named.


## Notes

**2026-11-10T20:39:29Z**

2026-11-10 unchanged in release 77673bfb8fcf; this release did not touch it. Followed by link key from 619db5f9e08e: rows 130655 (CHRG-117shrg45945.pdf), 138297 (CHRG-119shrg58674.pdf) and 138459 (CHRG-119shrg60657.pdf) are now rows 100076, 103985 and 104069, still on meetings 329124, 336584 and 337025.

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: unchanged in 77673bfb8fcf (rows 100076, 103985, 104069 still on Senate business meetings 329124, 336584, 337025, per the 2026-11-10 note); no commit names ct-uul8.
