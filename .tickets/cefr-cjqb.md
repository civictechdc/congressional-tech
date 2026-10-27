---
id: cefr-cjqb
status: closed
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


## Notes

**2026-10-27T14:02:57Z**

B11 contracts show original substitution changing attempts from selected 1 to fixture 99. Removed alternate test-environment/development-output/threaded route; all callers use existing bounded selected-native-leaf iterator. Focused project runner: 5 passed, 9 skipped (DOCSPEC_BINARY not configured); includes preserved original selected snapshot/order assertions and AST ratchet. Independent reviews pending.

**2026-10-27T15:38:48Z**

Local done:45-line production/test substitution deleted; selected native iterator is identical in every environment. Review enrollment concern fixed d3093739; all surviving target modules and provenance/repair CLIs enrolled.7 state/body contracts and50 store/ratchet checks pass.
