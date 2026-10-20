---
id: ct-9vtu
status: in_progress
deps: [ct-rcs8]
links: []
created: 2026-10-20T15:54:57Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Resume catalog adoption from verified local preparation

Exact adoption saves only the final qualified receipt. Before that point, interruption repeats dependency preparation and invokes already accepted catalog chunks because the existing checkpoint directory is not passed through.

## Design

Reuse existing chunk preparation checkpoints and exact input/requirements binding. Keep the current single catalog selector and native completion owner; add no second journal. Cache completed dependency preparation only if safely bound to the frozen input and implementation.

## Acceptance Criteria

Inject interruption after accepted preparation, resume without resubmitting completed catalog chunks; refuse changed input/schema/implementation. Preserve every row and mapping. Test locally, independently review, grade and integrate. No provider or full-corpus rerun.

