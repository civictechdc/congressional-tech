---
id: ct-ywz2
status: open
deps: []
links: []
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

