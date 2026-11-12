---
id: ct-yizl
status: open
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
