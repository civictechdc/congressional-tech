---
id: ct-15wc
status: closed
deps: []
links: [ct-zika, ct-qyey, ct-hfrv]
created: 2026-10-18T19:44:02Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Keep large detail panels responsive with explicit state

openDetail relies on a large shared reset sequence, source history builds all buttons, and technical filtering repeatedly formats every candidate value. Extract cohesive detail-session phases, bound source-list DOM and use bounded per-detail formatting reuse or debounce. Keep complete values and full-copy semantics.

## Acceptance Criteria

- Saved/original links appear before optional provenance; no eager full-record request, and late detail/review/origin/technical/copy responses cannot affect another source.
- Every source remains selectable with focus/role labels preserved while large-group DOM work is bounded.
- Technical search finds the same fields; values remain fully inspectable/copyable, formatting state is released on source change/close, and before/after work counters justify the simplification.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 5 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:182). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:26:38Z**

Detail setup/release now clears state, caches and heavy DOM; primary links precede optional provenance. Source lists render at most 20 selectable buttons and preserve navigation focus on late origin updates; 1,001-source fixture reaches its final source. Bounded formatting cache performs 10 formats plus 190 hits for repeated fixture searches, preserves oversized values uncached. Stale clipboard/network results cannot affect another or closed panel. Independent review approved; 56 focused checks, 138 integration checks before final focus refinement and built bootstrap smoke passed.
