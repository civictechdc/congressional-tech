---
id: ct-aq4w
status: open
deps: []
links: []
created: 2026-11-18T20:27:36Z
type: bug
priority: 1
assignee: mikewolfd
tags: [site, explorer]
---
# Site never shows recording durations or Public Law numbers

Found 2026-11-18 by the branch value review (.cache/archive-release/reviews/branch-value-20261118/b-ct-ddk/REPORT.md), checked against release ca6e7adbfacf. apps/site HearingDetail.tsx:221 formats rec.duration_s, but recordings.parquet has no duration column (columns: video_key, event_ids, tracks, recording_scope); durations are videos.parquet duration_seconds. SubjectDetail.tsx:71,122-123 and archive-entities.ts:476 read b.laws, but bills.parquet has no laws column; the number is public_law_number. Visitors therefore never see recording durations or Public Law numbers. Nominations also omit nominees silently instead of saying details are unavailable. Fixes exist on the archived branch archive/2026-11-18/codex/ddk-congress-replacement-20261106, commits 68b077ad and 57a6bc3c; port by hand onto current main (the branch is 1,226 commits behind), keeping main's newer entity columns. Front-end only; no model definition change.

## Acceptance Criteria

A hearing with a video shows its duration, a bill that became law shows its Public Law number, and a nomination without nominee rows says so; a site test covers each.

