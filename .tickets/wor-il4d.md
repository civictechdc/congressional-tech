---
id: wor-il4d
status: in_progress
deps: []
links: []
created: 2026-10-29T08:50:59Z
type: task
priority: 1
assignee: mikewolfd
---
# Release every model relation after its final native reader

Compute complete SQL dependencies with the maintained locked parser; retire unused lazy views and materialized steps safely, and orient corpus join builds.

## Acceptance Criteria

Fixture proves every actual reader remains available and no named step survives its true last reader; native raw-to-release guards and output parity pass; every physical join build is audited with bounded fixture plans.

