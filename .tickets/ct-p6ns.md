---
id: ct-p6ns
status: closed
deps: []
links: [ct-hfrv, ct-lvvr]
created: 2026-10-18T19:44:02Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Define review startup limits and preserve recovery failure rules

Optional review verification currently blocks all info with no deadline or response admission. Give it an explicit configurable deadline and expected-byte admission, using the existing review-unavailable state on policy failure. Document the different recovery rule: invalid recovery data still rejects catalog initialization; baseline-only fallback is not authorized by this ticket.

## Acceptance Criteria

- Hung and overlength review responses settle under declared limits; actual byte/digest/pair checks still decide acceptance.
- Optional review failure disables reviewed search and explains the error while existing original-catalog behavior remains available.
- Bad recovery hash/size/catalog/positions still fail closed, absent recovery stays valid, and one immutable catalog identity is retained.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 4 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:554). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:12:01Z**

Implemented and verified in browser batch 1. See docs/experiments/publication-remediation/browser.md. Focused Node suites cover lifecycle, rules, review policy, actual worker routes and recovery fail-closed checks; existing UI suite remains green.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3b).
- Grades: proposal 85 → 85, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
