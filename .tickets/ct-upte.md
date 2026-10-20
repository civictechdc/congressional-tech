---
id: ct-upte
status: in_progress
deps: [ct-l5q1]
links: []
created: 2026-10-20T07:43:10Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Reuse validated membership leaves during one update

The integrated4/40 fixture rereads the same shared membership leaf repeatedly: source-observation append performs84 native reads and48,566 logical rows at40 unrelated documents. Finite shared-leaf cost is expected; repeated reads of the same exact immutable leaf are avoidable.

## Design

Reuse a strictly bounded, exact-pin validated leaf within the maintained CatalogMemberships owner. Prefer one retained leaf or an existing bounded primitive. Preserve alias validation, duplicate checks, selected counts, update isolation and immutable old pins; do not change partition/resource limits.

## Acceptance Criteria

Red/green tests prove repeated alias queries sharing a leaf decode it once, changed pins or metadata revalidate, and eviction stays bounded. Re-run the retained4/40 integrated cases after the code change, report all counters and remaining shared-leaf amplification, prove exact values/IDs/publication hashes, and independently review.

