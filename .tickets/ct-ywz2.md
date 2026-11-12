---
id: ct-ywz2
status: closed
deps: []
links: [ct-jcnd, cat2-8ai9, ct-yizl]
created: 2026-11-10T03:26:30Z
type: task
priority: 2
assignee: mikewolfd
tags: [model, video, meetings]
---
# Recordings linked from committee pages belong to no meeting, and clips are not marked

284 recordings added on 2026-11-10 come from 274 House committee hearing, markup and calendar pages, none of which names an event number, so they count toward no meeting's coverage unless a match exists (YouTube rows of this shape went 394 to 678; 2,684 Senate rows unchanged). 19 of a seeded sample of 20 are the recording of the page's own proceeding. Six are clips under five minutes and recordings.parquet has no full-or-excerpt column. Source: .cache/archive-release/release-20261110/causes/video/recordings-284-*.json.

## Acceptance Criteria

Committee pages are linked to their meeting where the page identifies one, with the count linked and not linked recorded; recordings carry a full-or-excerpt marker or the reason they cannot.


## Notes

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: not started (no commit names ct-ywz2); recordings.parquet in 77673bfb8fcf still has no full-or-excerpt column.

**2026-11-12T05:29:00Z**

Closed:
- Added `model/sql/house-page-meeting-links.sql` (resolving House committee proceeding pages holding recordings either by a unique single-meeting proceeding document linked from the page or by parent `.house.gov` committee + proceeding date corroborated by substantive title/measure word overlap, vetoing misplaced markup/organizational videos on non-markup hearing pages in `entity-recording-matches.sql`) and wired both `house_page_meeting_links` and `senate_page_meeting_links` into `recording_page_meetings`.
- Measured on the 274 House committee pages / 284 recordings (`recordings-284-traced.json` against `46ebbdf8dcaf`): `216` of `274` House pages link to a canonical meeting (`58` unlinked: informal listening sessions, roundtables, member briefings, and field events with no canonical row in `meetings.parquet`, or undated pages), with `18/18` (`0` disagreements) between direct proceeding-document links and dated-committee-title links; `226` of `284` recordings link via `committee_page` (`228` of `284` total with `recording_matches`, `56` unlinked).
- Added `recording_scope` (`'full'`, `'excerpt'`, `'unknown'`, dictionary-encoded) to `recordings.parquet` (`model/sql/entity-recordings-matched.sql`, `model/registries/release-schema.json`, `docs/release-relationships.md`, `apps/site`) and updated `entity-meeting-coverage.sql` so asserted excerpt-only recordings count as `partial` (`excerpts_only`) rather than `present` (`full_recording`). Validated against all `2,460` curated `video_key`s in `recording_matches.parquet` (`2,008/2,009` = `99.95%` precision on `full` and `100/102` = `98.0%` on `excerpt` before curated override, `100.0%` with curated override; all 6 short clips in the 284 batch marked `'excerpt'`, short full business/organizational meetings marked `'full'`, and `0`-duration placeholders marked `'unknown'`). Added recordings with non-empty `event_ids` (`with event_ids`) remain human-reviewed at Gate 1 (`ct-zdj8` auto-traces only `empty event_ids` additions).

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
