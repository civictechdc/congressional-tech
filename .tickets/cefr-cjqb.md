---
id: cefr-cjqb
status: in_progress
deps: []
links: []
created: 2026-10-27T14:01:31Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B11: remove test-selected raw state inputs and ratchet surviving code

## Acceptance Criteria

All raw-state iteration reads selected native pins in every environment; no test-dependent branches or fixture paths in surviving raw components; existing ordering/snapshot assertions and focused runner pass.

