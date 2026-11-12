---
id: ct-yizl
status: closed
deps: []
links: [ct-jcnd, cat2-8ai9, ct-ywz2]
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, video, recordings]
---
# recordings.event_ids and recording_matches disagree on 66 rows: two owners of the video-to-meeting link

After the 2026-11-10 build, recordings with an empty event_ids but a linked recording_matches row (basis video_states_event_id) grew from 5 to 66 (61 of the 284 newly linked committee-page recordings match 62 meetings, e.g. youtube:0YtytQuMCT8 to event 119546). Coverage counts from matches, so the two disagree about whether a recording belongs to a meeting. Source: .cache/archive-release/release-20261110/causes/review-video/ and .cache/archive-release/release-20261110/causes/video/README.md.

## Acceptance Criteria

One of the two is the owner of the link and the other is derived from it (or removed); the disagreement count is 0 and a test holds it there.


## Notes

**2026-11-11T14:44:37Z**

validated 2026-11-11, left open: still two owners. DuckDB on 77673bfb8fcf: 67 recordings have empty event_ids but a recording_matches row with an event_id and basis video_states_event_id (69 with any basis); the filing counted 66 on the earlier build.

**2026-11-12T05:02:00Z**

Closed: `recording_matches` is now the single owner of published video-to-meeting links when Explorer inputs are present. `entity-recording-matches.sql` includes committee-page meeting links (`basis = 'committee_page'`, `score = 100`, `status = 'asserted'`) alongside `publisher_link`, `video_states_event_id`, and `curated`, and `entity-recordings-matched.sql` derives `recordings.event_ids` (and matched `video_key` rows) directly from `recording_matches_export` (`scope = 'event'`, `status IN ('asserted', 'claimed', 'decided')`, `decision NOT IN ('no_video_found', 'not_public')`), eliminating all 69 disagreements (`67` `video_states_event_id` + `2` other basis rows on `77673bfb8fcf` / `46ebbdf8dcaf`) while keeping `recordings_entity` Phase-2-only so `meetings.parquet` stays byte-identical when Explorer inputs are toggled. Enforced by `recording_event_link_mismatches = 0` in `explorer_invariants` and covered in `test_explorer_native_tables.py` and `test_phase2_model_entities.py`.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
