---
id: ct-p6aq
status: closed
deps: []
links: [ct-lvvr, ct-9at7, ct-bs70, ct-rckw]
created: 2026-10-18T19:44:01Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Reduce repeated browser search normalization and match storage

text(), matches(), search() and observation matching reserialize/case-fold complete values, and search retains every matched group for one result page. Reduce repeat work with an explicitly budgeted representation and count-plus-page accumulation. Assess common-field indexing only if it preserves arbitrary-field semantics and shows useful total cost.

## Acceptance Criteria

- Same-source AND, review pins, null filters, scope, Unicode, nested JSON representation, recovered names, duplicate observations and ordering match reference results.
- Report cold/repeated transfer, decode/normalization operations and retained bytes on controlled fixtures.
- Do not force a new index or unbounded cache: keep and document an exact full-scan fallback when the alternative is not worthwhile.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 6 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:541). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:22:07Z**

Count-plus-page accumulation bounds matched group storage at twice page limit. Budgeted scalar/observation normalized text removes repeated formatting; exact scan fallback remains, no extra field index. Expanded Python-reference queries verify same-source AND, Unicode/nested JSON plus existing review/null/recovery/order checks. 18 catalog/worker tests passed; counters in browser.md.
