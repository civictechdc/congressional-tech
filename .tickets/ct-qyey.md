---
id: ct-qyey
status: closed
deps: []
links: [ct-15wc, ct-bs70]
created: 2026-10-18T19:44:02Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Separate provenance graph construction and bound repeated work

sourceContext and renderOrigin mix relationship assembly, repeated deduplication, graph paths and DOM rendering. Extract a pure evidence graph, use keyed deduplication and avoid unnecessary path-array copying; check incremental pages without inventing relationships.

## Acceptance Criteria

- Cycles, duplicate URLs/redirects, ambiguous titles, convergent paths, recovered candidates and ancestor references preserve exact evidence meaning and deterministic display order.
- Repeated origin pages deduplicate equivalent display links without discarding competing observations; failure/retry and stale-controller guards retain prior context.
- Report graph visits/path-copy/render work on large fixtures and use that evidence to choose incremental versus complete redraw.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 4 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:592). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:26:38Z**

Extracted pure provenance assembly, keyed redirect/page deduplication and one reverse BFS with stable shortest-path ordering. Preserves competing titles/link labels, exact URL protocols and source-page retry context. 2,000-edge fixture: 2,001 vertex visits, 4,000 edge visits, zero partial-path copies versus 1,999,000 copied entries previously. Full redraw retained when new evidence changes earlier relationships. Independent review approved; 56 focused UI/graph/cache tests and actual built bootstrap smoke passed. Evidence: docs/experiments/publication-remediation/detail-ui.md.
