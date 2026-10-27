---
id: cef-adn6
status: in_progress
deps: []
links: []
created: 2026-10-27T12:00:28Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, C7]
---
# C7: bind the existing native client to SQL jobs

## Acceptance Criteria

SQL job calls reuse NativeDatasets binary verification and process invocation, require explicit limits and artifact pins, refuse remote lifecycle configuration, and preserve completed output identities on native failure. Project runner covers the injected executable adapter.

