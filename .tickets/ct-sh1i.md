---
id: ct-sh1i
status: closed
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

**2026-11-12T06:00:00Z**

Fixed and re-measured on the pinned 25,190-row `committee-rosters` generation (`32ac9696`): (1) `model/sql/entity-rosters.sql` labels dated seats whose member's recorded service terms ended before `edition_date` with `entry_label = 'after_departure'` (unlabelled departed seats: `19 -> 0`; all 19 115th Congress seats of McCain 6, DeSantis 9, and Evan Jenkins 4 on `2018-10-29` are now labelled alongside the 2 upstream-labelled seats); (2) unprinted source ranks stay `NULL` rather than synthesizing sequential integers (`1,147` archive-made ranks `-> 0`: 254 Directory seats in 113th–117th, 441 archived 118th Senate seats, 2 118th `directory-manual` seats, and 450 119th Senate seats; `committee_roster` recipe and `apps/site` sort leadership ahead of untitled `rank IS NULL` seats); (3) 118th Congress committees covered by archived chamber files (`file` dated `2024-05-01` and `caller` dated `2024-09-11` extracted from their Internet Archive URLs) drop the 25 stale `directory-manual` (`2024-04-25`) seats across the 24 mixed non-joint committees (`25,190 -> 25,165` rows, `0` mixed non-joint snapshots, `0` double chairs, `0` duplicate party ranks, while preserving `820` `directory-manual`-only seats with `6` `entry_label = 'corrected'` rows keeping `printed_entry`, plus `6` `corrected` rows in 114th–117th). Updated `release-schema.json`, `docs/release-relationships.md`, `docs/congress-explorer-personas.md`, and `docs/engine-first-architecture.md`.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
