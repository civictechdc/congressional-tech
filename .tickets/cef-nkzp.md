---
id: cef-nkzp
status: closed
deps: []
links: []
created: 2026-10-29T08:02:47Z
type: bug
priority: 0
assignee: engine
---
# Stream full-corpus model evidence through narrow join builds

The first full raw model failed in body_evidence after 75.8 s on a hash-join allocation. Preserve wide body/capture rows as probe inputs and build narrow fact/verification relations, without changing evidence semantics or resource budgets.

## Acceptance Criteria

Native fixture preserves copy, conflict and missing-fact behavior, and physical plans never build wide body/capture rows. Focused model checks and one code review pass; lead runs a fresh standard-profile model attempt.


## Notes

**2026-10-30T14:32:56Z**

Completed narrow join build streaming in body_evidence and merged to main.
