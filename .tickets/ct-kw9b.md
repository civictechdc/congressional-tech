---
id: ct-kw9b
status: closed
deps: []
links: []
created: 2026-10-30T14:32:30Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, model, completeness, track1]
---
# T1.4: Add Phase-2 work-list completeness & lake schema pins in archive_model.py and profile-completeness.sql

Add Phase-2 work-list completeness & lake schema pins in packages/viewer_publication/src/viewer_publication/archive_model.py and model/sql/profile-completeness.sql:
- Include meeting_records and appearance_records in lake_versions when include_entities is enabled.
- Check their pinned parser version work lists in model/sql/profile-completeness.sql.

## Acceptance Criteria

When include_entities is enabled, archive_model.py pins meeting_records and appearance_records in lake_versions and profile-completeness.sql verifies their parser version work lists.

