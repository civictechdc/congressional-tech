---
id: cefr-ndu5
status: in_progress
deps: []
links: []
created: 2026-10-28T11:12:40Z
type: bug
priority: 1
assignee: raw
parent: cef-wylm
---
# Keep Linux parser address-space budget above initialized mappings

Owner portability correction: set the persistent parser child address-space ceiling to its initialized virtual size plus the configured budget, once after imports/protocol setup; retain the supervisor RSS ceiling and reject an inherited finite hard limit that cannot fit.

## Acceptance Criteria

Fake large-VSZ and inherited-limit fixtures pass; persistent actual worker keeps one ceiling across inputs; existing parser/resource focused tests pass; fresh CODE review; release reruns the named Linux cases.

