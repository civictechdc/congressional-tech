---
id: ct-yymr
status: open
deps: []
links: [cef-rmye]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, pipeline, daily, d4, track3]
---
# T3.1: Wire meeting_records and appearance_records into daily.py and archive_publish_job.py

Extend packages/congress_api/src/congress_api/lake/daily.py and packages/viewer_publication/src/viewer_publication/archive_publish_job.py (completed_daily_inputs) so automated daily runs refresh and pin meeting_records and appearance_records alongside captures, readings, and filename_readings.

## Acceptance Criteria

Daily production refreshes and pins 5 tables (captures, readings, filename_readings, meeting_records, appearance_records) and archive_publish_job.py forwards all 5 pins when publishing.

