---
id: cefr-r8vy
status: in_progress
deps: []
links: []
created: 2026-10-28T20:59:03Z
type: bug
priority: 1
assignee: raw
---
# D2: use exact listing size when historical capture size is absent

The full owner execute refused 364193 bodies with exact listing Size+ETag because copy admission and pending GET size still require raw capture stored_bytes. Apply the owner-approved exact-key size fallback without weakening conflict or no-GET guards.

## Acceptance Criteria

Fixture first covers absent capture size and MD5, missing listing size or ETag, size and MD5 conflicts, and unrecorded suffix refusal; focused project-runner tests and one code review pass; fresh exact owner commands prepared without live operations.

