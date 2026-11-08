---
id: ct-0mqc
status: open
deps: []
links: [ct-klyz]
created: 2026-11-08T13:54:03Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, youtube, pipeline]
---
# Weekly hearing-to-video matcher reads a meetings file nothing refreshes

Since ct-klyz (ff52a6c0, Nov 4) removed the weekly Congress.gov meeting fetch, update-data.yml still runs gpo-match (line 115) and congress-committees (line 166) against pipeline-data/congress_meetings.jsonl.gz. On 2026-11-08 that file held 18,142 meetings with a latest update stamp of 2026-10-30, so meetings announced since then give the matcher no Congress.gov evidence. If the file is absent, gpo_match.load_meetings only logs a warning and skips all Congress.gov evidence (gpo_match.py:52), so match quality drops silently. Fix: read meetings from the lake (the archive's house-/senate-meeting-records), as archived branch r4-b did (refs/archive/20261108/r4-b, commit 1b87e606, meeting_export.py), and refuse instead of warn when the source is missing. Do not revive r4-b's scheduled fetch-meetings workflow.

