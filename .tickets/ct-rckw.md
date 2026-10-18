---
id: ct-rckw
status: closed
deps: []
links: [ct-p6aq]
created: 2026-10-18T19:44:02Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Validate literal dates and integer viewer pagination

filenameDate can present a normalized impossible date as a real date; goToPage/restore/search clamp numeric input without a shared integer rule. Keep literal invalid dates and normalize page/limit consistently at UI and reader boundaries.

## Acceptance Criteria

- Invalid calendar dates remain literal; valid leap day and UTC date display remain correct.
- Fractional, invalid, infinite, zero, negative and oversized page/limit values follow one documented integer rule across URL, controls, reader slices and returned metadata.
- Valid existing links and result ordering remain unchanged.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 3 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:603). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:12:01Z**

Implemented and verified in browser batch 1. See docs/experiments/publication-remediation/browser.md. Focused Node suites cover lifecycle, rules, review policy, actual worker routes and recovery fail-closed checks; existing UI suite remains green.
