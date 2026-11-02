---
id: ct-sulv
status: open
deps: []
links: [ct-9s7b]
created: 2026-11-02T15:33:09Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recordings, captions]
---
# Recordings publish one caption body as both live and caption productions

impl-r4-c 2026-11-02: 765 recordings publish one body under both live and caption productions, because two recording-source registry URL patterns match one fetch. Separate from ct-9s7b.

## Acceptance Criteria

Each fetched body maps to exactly one (format, language, production) per recording; registry patterns are disjoint or ranked; a native check refuses a body published under two productions.

