---
id: cefr-iyv6
status: in_progress
deps: []
links: []
created: 2026-10-28T22:29:13Z
type: task
priority: 0
assignee: raw
---
# D2: bounded parser pool and large commit batches

Lead220128 approved bounded persistent ParserWorker pool, four-times-worker in-flight window, per-worker read and memory budgets, measured8/16/32, and2048–4096 commit batches under existing actual-size cache preflight. Reuse maintained generic worker and R2 transport/prefetch helpers; no new dependencies.

## Acceptance Criteria

Fixture-first concurrency, ordered main-thread decisions, budget refusal and restart anti-join checks pass; one CODE review passes; local bounded measurements and exact fresh owner commands prepared; no live job run byraw.

