---
id: ct-l9g0
status: open
deps: []
links: [cef-9e9w, ct-oxg6]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ci, runtime, bindings, track3]
---
# T3.3: Consolidate the engine runtime pin file across setup and check scripts

Per docs/plans/bindings-20261025.md §3.1: replace environment-variable digest lookups in .github/scripts/setup-native-runtime.py, .github/scripts/setup-local-job-runtime.py, and .github/scripts/check-native-runtime.py with one committed pin file holding the engine revision and per-OS SHA-256.

## Acceptance Criteria

One committed runtime pin file holds the engine revision and per-OS SHA-256 digests, and setup-native-runtime.py, setup-local-job-runtime.py, and check-native-runtime.py read from it.

