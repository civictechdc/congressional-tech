---
id: ct-0mqc
status: closed
deps: []
links: [ct-klyz, ct-q4e2, ct-4jms]
created: 2026-11-08T13:54:03Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, youtube, pipeline]
---
# Weekly hearing-to-video matcher reads a meetings file nothing refreshes

Since ct-klyz (ff52a6c0, Nov 4) removed the weekly Congress.gov meeting fetch, update-data.yml still runs gpo-match (line 115) and congress-committees (line 166) against pipeline-data/congress_meetings.jsonl.gz. On 2026-11-08 that file held 18,142 meetings with a latest update stamp of 2026-10-30, so meetings announced since then give the matcher no Congress.gov evidence. If the file is absent, gpo_match.load_meetings only logs a warning and skips all Congress.gov evidence (gpo_match.py:52), so match quality drops silently. Fix: read meetings from the lake (the archive's house-/senate-meeting-records), as archived branch r4-b did (refs/archive/20261108/r4-b, commit 1b87e606, meeting_export.py), and refuse instead of warn when the source is missing. Do not revive r4-b's scheduled fetch-meetings workflow.


## Notes

**2026-11-08T17:16:49Z**

2026-11-08 closed: merged in af245a6a (from 945bbd6a). gpo-match and congress-committees read meetings.parquet and committees.parquet from the current public release (hash- and size-checked), and exit 2 when the source is missing, altered or empty. On real data: 16 more hearings matched to a full recording, none lost recording status. GitHub validate-explorer green on bee5fd97 (run 42502108566). New meetings reach the matcher only once capture runs again (ct-4jms).
