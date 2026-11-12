---
id: ct-wy4c
status: closed
deps: []
links: [ct-17op]
created: 2026-11-10T03:26:29Z
type: task
priority: 3
assignee: mikewolfd
tags: [mods, witnesses, owner-decision]
---
# Decide whether witness rows show military rank and credentials

After ct-rg34, 299 more MODS witness rows no longer show a rank or credential (47 rank, 291 credential). The live release already drops rank on 944 rows and credentials on 6,474. Nothing is lost in raw. Whether a witness's rank or credential belongs in name, position or a field of its own is an owner decision. Source: .cache/archive-release/release-20261110/causes/review-C/REVIEW.md.

## Acceptance Criteria

The owner's decision is recorded here and, if rank or credentials are kept, a parser ticket is filed with the measured row counts.


## Notes

**2026-11-10T05:38:12Z**

2026-11-10 owner decision (questions dialog): rank and credentials go in their own field, not the name and not dropped. Reviewer's corrected count: 299 rows this release (47 rank, 291 credential); live already drops rank on 944 rows and credentials on 6,474. The parser work joins ct-6mvl's version step.

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: the owner's decision is recorded (2026-11-10: rank and credentials in their own field), but the parser ticket the acceptance asks for does not exist: ct-6mvl's text and acceptance do not mention rank or credentials, and the MODS release branch claude/ct-mods-and-member-appearances adds no such field (its SQL drops credentials as words, appearance-people.sql:4-5). Remains: file or fold the parser work (own field, 299 + 944 rank and 6,474 + 291 credential rows) into ct-6mvl's acceptance, then close this.

**2026-11-11T14:57:19Z**

2026-11-11 (session congress-1): the parser ticket this decision asks for is ct-17op (filed after the release session's audit found the follow-up was not on ct-6mvl).

**2026-11-12T02:42:00Z**

Closed: both acceptance criteria are met — the owner decision (`2026-11-10`: `rank` and `credentials` go in their own fields, not in the name and not dropped) is recorded above, and follow-up parser ticket `ct-17op` was filed `2026-11-11T14:57:19Z` with the measured row counts (`299` MODS rows in `ct-rg34` — `47` rank, `291` credentials — plus `944` rank and `6,474` credential rows already dropped on live across sources).
