---
id: cefr-iyv6
status: closed
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


## Notes

**2026-10-28T23:24:54Z**

ONE CODE review requested one correction: concurrent prefetch plus active range parsers could exceed64 GETs. Confirmed with94926bf4 RED mixed-window fixture;4589322b reserves parser slots and64 focused production-offline checks pass. No other concerns; small fix needs no second review round. Prior337 producer/storage cases passed. Owner measured8/16/32 at23.0/65.2/98.4 bodies/s, with2/1/1 pending reads and0 transport errors/0 unreadables. Measurements predate the GET allocation correction and have an R2 edge-warming caveat. Exact fresh owner32 production command and20GiB native/24GiB physical monitor delivered at codex-raw/run2/d2-production-32/owner-command.txt. No live job run by raw.
