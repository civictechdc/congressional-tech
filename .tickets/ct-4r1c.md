---
id: ct-4r1c
status: closed
deps: []
links: [ct-ylaw, ct-atjy, ct-70kc]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Validate recovery admission evidence with bounded reads

verify_import reads several complete JSON documents and an event log, then relies on nested dictionary shapes. Malformed or oversized evidence can allocate unnecessarily or fail with poorly located key/type errors.

Source: scripts/dispatch_corpus_recovery_publication.py:32-69.

## Acceptance Criteria

Declare supported evidence shapes and byte/event limits; stream bounded event validation where practical. Report the file and invalid field while preserving original errors. Reject oversized, duplicate-completion, wrong-batch, missing-pin and count/hash mismatches before writes. Keep current valid evidence and domain coverage checks.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 1 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:236). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:15:51Z**

Implemented read-only bounded admission helper: 64 MiB JSON/total events, 1 MiB events, 100000 events; explicit object/list/field/counter/hash checks; streamed event validation rejects duplicate completion/pins, missing/wrong pins, malformed counts/shapes and changed evidence with file/field errors preserving JSON parse causes. Helper included in restart pins. 17 dispatcher tests plus 5 continuation subtests passed before helper pin path addition; synthetic continuation repo fixture needs helper copy for updated pins.

**2026-10-18T20:15:58Z**

Updated synthetic continuation repository to carry newly pinned helper; complete 17 tests and 5 continuation subtests pass with restart pin addition.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch d8z3a).
- Grades: proposal 78 → 81, work 82 → 84.
- Problem: A non-object `value` in `write_intent` or `write_verified` events raises a bare AttributeError from `event.get("value", {}).get(...)` (`admission.py:218,220,223`).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3a/d8z3a-verdicts.md:74
- Covered by: WS4 (ct-70kc), which validates the event shape once.
- See docs/reviews/2026-10-24-ticket-audit/README.md
