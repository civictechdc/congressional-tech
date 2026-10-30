---
id: ct-zy2s
status: closed
deps: []
links: []
created: 2026-10-30T14:32:30Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, model, schema, track1]
---
# T1.2: Complete coverage & gaps metadata on entity files in archive_format.py and release-schema.json

Complete coverage & gaps metadata on entity files in packages/viewer_publication/src/viewer_publication/archive_format.py (_execute) and model/registries/release-schema.json:
- Add coverage SQL queries in _execute for meetings.parquet (congress range), rosters.parquet (congress range), members.parquet (terms date range), committees.parquet (names date range), and witnesses.parquet.
- Add the 119th-Congress-only coverage gap note to nominations.parquet in model/registries/release-schema.json.

## Acceptance Criteria

release.json populates coverage ranges for meetings, rosters, members, committees, and witnesses, and nominations.parquet carries the 119th-Congress-only coverage gap note in release-schema.json.

