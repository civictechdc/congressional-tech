---
id: ct-qdkd
status: open
deps: [ct-q968]
links: []
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Expose native progress and combined staging capacity

Use maintained plan/inspect and native counters for pending/completed work. Admit application preparation plus native scratch/headroom before expensive work. Avoid a second lifecycle or monitoring engine.

## Acceptance Criteria

Operator command reports exact operation, reusable phases and actionable refusal without secrets or extra payload scans. Tests cover early insufficient capacity, active/completed/failed operation, unchanged limits and changed configuration.

