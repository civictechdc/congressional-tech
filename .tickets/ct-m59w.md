---
id: ct-m59w
status: closed
deps: []
links: [ct-fw0m, ct-1dsp, ct-idhg, ct-zkzt, ct-ylaw, ct-qqk2]
created: 2026-10-18T19:44:01Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Reuse exact transfer proof without retaining unused receipts

Guarded JSON writes always create transfer receipts that put_json and journal callers discard; store_recovery_index then fully reads back the same object again. Replayed file transfers can also repeat current-version HEAD checks. Make receipt ownership short-lived and consume one exact current proof where appropriate. Sources: guarded_recovery_publication_client.py:49, publish-viewer-r2.py:174-195, recovery_publication_continuation.py:124-146.

## Acceptance Criteria

Measure full reads, version HEADs and retained receipt/lock counts for payload, JSON, journal and replay paths. Guarded JSON reuse may avoid only duplicate readback; plain/unsupported clients keep independent full proof. Wrong issuer/bucket/key/bytes/hash/ETag, copied/serialized proof and changed current version never authorize skipping verification. Ignored receipts have bounded lifetime; any lock cleanup preserves exclusion for concurrent same-key writers. Keep full read after restart and original replay conditions.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 6 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:513). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:22:54Z**

Exact guarded recovery JSON proof now avoids duplicate full GET; plain SDK fallback keeps full independent readback. Weak issuance registry retains zero ignored receipts; waiter-counted key locks clean only after last owner/waiter.51focused tests+2subtests pass incl all wrong request fields, forgery/issuer/current-version/single-use refusal,24same-key concurrent writers and restart full reconciliation. Replay retains conservative version HEAD checks; cost receipts expose those counts rather than weakening original replay conditions.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3b).
- Grades: proposal 76 → 70, work 86 → 80.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
