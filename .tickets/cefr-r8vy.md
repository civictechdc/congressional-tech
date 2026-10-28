---
id: cefr-r8vy
status: closed
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


## Notes

**2026-10-28T21:06:39Z**

Owner exact-LIST Size authority205744; fixtureb96d1d87 reproduced2positive failures/3negative passes; implementation1a291b89 passed54focused. ONECODE review REQUEST CHANGES exactlyone missing-LIST-ETag/capture-MD5 concern;6969f121 reproducedboth inventory modes;1bf4e998 fixedguard. All56focused checks pass through projectrunner/current0cb; original captures preserved; size/MD5/suffix negatives intact. Fresh full-listed-size specs/commands prepared, no real GET or write executed byraw. Review run2/d2-size-review/review.md; no extra round for narrowguardfix.
