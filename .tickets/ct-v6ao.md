---
id: ct-v6ao
status: open
deps: [ct-2d3k, ct-tenb]
links: [ct-d3un]
created: 2026-10-19T16:40:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [overlap-followup]
---
# Reduce normal publication checkpoint work with crash proof

Validated remote restore now checkpoints once, but normal intent/verified events still rewrite growing full continuation state, and protected after_write flushes again (continuation214-217,385-412;attempt313-316). Retained success fixture has 548 state dumps/61.4M serialized characters; matched fresh publication was 7.5% slower. Resume gains do not prove normal success gains.

## Acceptance Criteria

- Measure request counts/bytes, state serialization characters/calls, fsyncs, controlled-latency duration and retained scratch before/after on the same pinned fixture.
- Use one compact derived checkpoint/update owner where crash proof permits; do not remove write-ahead intent, exact readback, original condition, nonce/chain or concurrent-append fences.
- Interruption before/after PUT, readback, protected-version advancement and verified-event commit remains recoverable without duplicate mutation or invented verification.
- Bound event count 16384, per-event 1 MiB, history 64 MiB and state 32 MiB remain; informational events remain valid.
- Report measured normal versus resume effects separately, with no full-catalog or aggregate speed claim absent evidence.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/recovery_publication_continuation.py:37:Continuation.flush, scripts/recovery_publication_continuation.py:73:Continuation.record, scripts/recovery_publication_continuation.py:205:DurableJournal.record, scripts/viewer_publication_attempt.py:200:publish.after_write. See docs/package-overlap-rescore-20261019.md for the full grade map.
