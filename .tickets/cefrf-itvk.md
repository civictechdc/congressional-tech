---
id: cefrf-itvk
status: in_progress
deps: []
links: []
created: 2026-10-28T23:45:03Z
type: task
priority: 2
assignee: mikewolfd
---
# D2: completion-driven parser replenishment and asynchronous page prefetch

Owner/lead234305Z supersedes233611Z: keep32 workers,512MiB cap,64-GET admission, sequential per-body ranges and all identity/encoding/retry/pending rules. Replenish viaFIRST_COMPLETED; final output ordering belongs to the native batch writer. Page prefetch must overlap work without blocking parser submission. Use the maintained R2Store helper. Build in isolated raw-fast while33630 uses frozen raw source; lead stops and relaunches at a commit boundary.

## Acceptance Criteria

Fixture-first blocked-first replenishment and async-prefetch tests pass under bounded queues/cache/request slots; native batch output stays sorted; error/durable-decision semantics stay intact. One small focused CODE review, then disjoint cold current-versus-patched N32 samples with bodies/s, bytes/s, rangep50/p95, retries and physical peak. Fresh production command, no live job by raw. D1 heavy qualification waits until this step is in production.
