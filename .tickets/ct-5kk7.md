---
id: ct-5kk7
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T20:47:30Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness, release-blocker]
---
# Meetings lose their videos when a Congress.gov meeting record is first fetched with an unchanged update date

Nightly candidate ef4c1632 vs live e4538f00: meetings 102827, 102917, 103028, 103081, 103182, 103185, 103226, 337959 go from 2 videos to 0 (meetings.videos 9, recordings removed 8, recording_matches removed 16, meeting_coverage recording/caption rows). Their congress_gov_updated is unchanged; the record first fetched 2026-10-30 wins the tie as newest. Not yet known whether the new API bodies omit videos or the parser/model drops them. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/10-possible-defect-meeting-videos.json, .cache/archive-release/nightly/20261104T174328Z/causes/evidence/11-meeting-coverage.json.

## Acceptance Criteria

Read the lake meeting_records rows (old and new body) for the 8 meetings and state which side drops videos. If the API omits them, a newer body with the same updated stamp must not erase videos stated by an older body (or the release states why). Fixture for the tie case; rebuilt candidate keeps the videos or carries an explained cause.

