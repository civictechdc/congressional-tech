---
id: ct-sh1i
status: open
deps: []
links: []
created: 2026-11-10T03:26:29Z
type: bug
priority: 2
assignee: mikewolfd
tags: [rosters, model, ct-8cno]
---
# Historical rosters: unlabelled departed seats, archive-made ranks, and a merged 118th

Inside the 22,217 roster rows first published by ct-8cno (release cause review 2026-11-10, .cache/archive-release/release-20261110/causes/reference/ and .cache/archive-release/release-20261110/causes/review-DE/REVIEW.md): (1) 19 seats of departed members in the 115th Congress carry no after_departure label (e.g. McCain as Armed Services Chair); (2) 697 Directory seats carry a rank the source does not state (the first draft said 254); (3) the 118th is a union of two dated snapshots, giving two double chairs and eight rows with a wrong printed state.

## Acceptance Criteria

Each of the three counts is re-measured at zero or explained row by row; a rank the source does not print is either absent or labelled as derived; the 118th publishes one dated edition per row.


## Notes

**2026-11-10T05:38:12Z**

2026-11-10 correction from the recount on release 619db5f9e08e: 697 new seats carry an archive-made rank, of which 254 are Directory seats of the 113th to 117th, 441 come from archived Senate files and 2 from manual readings; the 118th joins three sources, not two; the 19 unlabelled departed seats are confirmed.

**2026-11-11T14:43:34Z**

validated 2026-11-11, left open: no change to model/sql/entity-rosters.sql or the roster inputs since the 2026-11-10 recount (the three counts stand: 19 unlabelled departed seats, 697 archive-made ranks, the 118th joined from three sources). Also stale, from closing ct-8cno: docs/congress-explorer-personas.md:21 and :217 still say rosters are 119th only (2,973 rows), and docs/engine-first-architecture.md:308 says roster history before the 119th waits on spicy-regs; the live release has 25,190 rows over 113-119.
