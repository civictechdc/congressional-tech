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

Owner/lead234305Z supersedes233611Z: keep32 workers,512MiB cap,64-GET admission, sequential per-body ranges and all identity/encoding/pending rules. Replenish viaFIRST_COMPLETED; final output ordering belongs to the native batch writer. Page prefetch must overlap work without blocking parser submission. Use the maintained R2Store helper. Lead002059Z reports33630 endedfailed on R2 throttling: add same-key synchronous read serialization and a targeted five-attempt SDK GET throttle budget, preserving unrelated error and PUT behavior. Build in isolated raw-fast; the lead launches one fresh production command after the focused review.

## Acceptance Criteria

Fixture-first blocked-first replenishment and async-prefetch tests pass under bounded queues/cache/request slots; native batch output stays sorted; error/durable-decision semantics stay intact. One small focused CODE review, then disjoint cold current-versus-patched N32 samples with bodies/s, bytes/s, rangep50/p95, retries and physical peak. Fresh production command, no live job by raw. D1 heavy qualification waits until this step is in production.

## Notes

**2026-10-29T01:16:34Z**

Local implementation/review complete at897ddbf6. One CODE APPROVE after419e9acb→897 metadata fix;364 broad PASS,129 related PASS,71 merged seams PASS. Blocked: owner live cold baseline/fast arms or fresh production launch; exact sealed commands are in scratch/codex-raw/run2/d2-fast-cold/owner-commands.md and d2-fast-production-32/owner-commands.md. Metadata-only cohort96521 passed5.350s/319997848physicalB,6144 each/zero overlap/excluding committed+prior sample. No new throughput claim or raw live launch.
