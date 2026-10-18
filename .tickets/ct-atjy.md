---
id: ct-atjy
status: closed
deps: []
links: [ct-idhg, ct-ylaw, ct-1mbc, ct-4r1c]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Validate and bound publication continuation state

Continuation loads nested JSON without checking its version/shape; record assumes legal transitions. DurableJournal.restore validates links/binding but materializes every listed key and event without count/byte bounds, and ignores journal version. Give these persisted inputs a small validated state/event model and clear limits before applying restored state. Sources: recovery_publication_continuation.py:21,48,73,160,182.

## Acceptance Criteria

Reject unsupported versions, malformed fields, illegal write transitions, escaping saved names and excessive state/history with specific diagnostics before publication mutation. Enforce event-count, event-byte and total-byte limits while listing/reading; validate a full accepted prefix before checkpointing it. Keep binding/chain/nonce/condition assertions and legitimate informational events. State that tail deletion lacks an independent terminal anchor; add such a guarantee only if required. Document atomic-save versus directory/power-loss durability and preserve required local dispatcher checkpoints.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 11 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:256). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:20:49Z**

Implemented bounded versioned continuation/event model and legal intent/verified/refused transitions, saved-path/symlink confinement,32MiB state/16,384events/1MiB event/64MiB history limits. Full journal prefix validated before one checkpoint; nonce/binding/chain/conditional fences preserved.64tests+7subtests passed incl runner loss/recovery/dispatcher and adversarial state/limits. Tail deletion has no independent terminal anchor; save vs flush power-loss durability documented.

**2026-10-18T20:23:10Z**

Journal validation and single-checkpoint restore merged. Fresh-phase count/path checks remain in progress with the preparation proof-hook change; keep this ticket open until its boundary tests merge.

**2026-10-18T20:32:53Z**

Fresh-phase limits and path refusal merged from 9a1baed and independently reviewed. Integrated continuation, attempt, and guard suite: 57 passed. Both new-phase and restored-state checks now verified.
