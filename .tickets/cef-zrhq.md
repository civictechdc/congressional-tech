---
id: cef-zrhq
status: in_progress
deps: []
links: []
created: 2026-10-27T18:29:08Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine-first, C0]
---
# Require one explicit native runtime before the offline test lane

## Acceptance Criteria

production-offline refuses before pytest with one actionable setup error for missing/invalid DOCSPEC_JOB_CONFIG; a verified pinned local runtime passes. No silent skip or implicit scratch default, remote/credential configuration refused before credential loading.

