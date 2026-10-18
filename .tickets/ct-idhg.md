---
id: ct-idhg
status: closed
deps: []
links: [ct-sv16, ct-atjy, ct-m59w]
created: 2026-10-18T19:25:05Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Reduce publication journal cost without weakening recovery

The retained fixture records 548 journal PUTs and 548 full journal GETs for 273 publication writes. Each event rewrites growing journal state while holding the journal lock. Remote latency savings are not measured.

Source: scripts/recovery_publication_continuation.py:37 (Continuation.flush) and :205 (DurableJournal.record). Compare a smaller durable event representation or safe checkpoint policy before changing it.

## Acceptance Criteria

Measure request counts, serialized bytes, local durability work and controlled-latency duration before and after. Preserve write-ahead intent, ambiguous-write reconciliation, restart refusal rules, concurrent-writer protection and all runner-loss cases. No new automatic retry or weaker publication verification.

<!-- grade-followup:start -->
## Grade review follow-up

Continuation.flush/record, publish.after_write and DurableJournal record/restore cost.

- Compare request, byte, serialization/fsync and controlled-latency counts without removing required crash boundaries. Rebuild validated restore state in memory and checkpoint once where safe; preserve intent-before-PUT, conditional nonce fencing and all uncertainty/restart tests. Coordinate state validation and receipt lifecycle without making them artificial prerequisites.

[Function scope and checks: 7 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:428). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:20:49Z**

Measured before/after same pinned source/runtime1ms modeled request fixture; receipts control-costs.json and control-journal-after.json. Validated restore now checkpoints write state once instead of replay-flushing every event, preserving local event evidence and all remote write-ahead PUT/full readback boundaries.64tests+7subtests pass incl ambiguity, process-loss, nonce/concurrent append and fresh reconciliation. Request counts and normal crash durability retained.
