---
id: ct-hm4b
status: closed
deps: []
links: [ct-lu4i, ct-zkzt, ct-zb9y, ct-qqk2]
created: 2026-10-18T19:44:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Bound publication control reads and preserve response errors

read_identity and verify_recovery_status read complete remote JSON without a supported byte ceiling; the latter checks expected bytes only after allocation. Public body reads happen outside open_public retry handling. Add a shared bounded control/status read policy with precise length/error handling; do not turn required complete verification into partial sampling. Sources: publish-viewer-r2.py:38,61,108 and public probe/status call sites.

## Acceptance Criteria

Define justified per-kind limits and enforce declared length plus actual streamed bytes before large allocation. Cover oversized, truncated, appended and malformed R2/public responses; close all response bodies on success/failure. Preserve raw digest, optional absence, complete hash/CORS checks and bounded read-only retries; do not add mutation retries. Document whether body-read failures are retried by any caller.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 3 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:400). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:15:08Z**

Bounded per-kind streamed control reads now check declared/actual/exact descriptor lengths and close bodies; raw digest/full hash/CORS semantics retained. Oversize/truncation/appended/malformed tests plus publication/recovery matrix: 82 tests and 2 subtests passed. Opening retries only; body-read errors propagate without mutation retry. Ceilings documented in durable-publication.md.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3a).
- Grades: proposal 82 → 82, work 86 → 86.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
