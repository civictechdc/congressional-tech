---
id: ct-5kb2
status: closed
deps: []
links: [ct-7uit]
created: 2026-10-20T16:20:58Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
---
# Batch dependency adoption without repeating per-row Arrow setup

The live initial catalog import spends its preparation phase constructing one-row Arrow batches and dependency tables. Synthetic 10k staging takes38.59s baseline versus14.25s with batched input; the safe existing byte-bounded batching route cuts the representative2k case from7.43–7.85s to3.30s while retaining exact staged values.

## Design

Reuse maintained byte-bounded chunk iteration and dependency_tables for bounded groups. Preserve row order, source_orders, IDs, aliases, duplicate/null values, schema checks and native lifecycle. Do not add concurrency or raise resource limits.

## Acceptance Criteria

Red/green or differential exact staging tests for ordinary and explicit source order, duplicate IDs, null/nested/large occurrence rows and refusal boundaries. Measure the same bounded fixture before/after, report memory/batching overhead and no production throughput claim. Independent review before replacing the running preparation; preserve all source files and existing native data.


## Notes

**2026-10-20T16:36:35Z**

Reviewed implementation e23de564 preserves exact staged values and native inputs. Synthetic 10k staging:36.26s to14.45s; no production throughput or peak-memory claim.112 focused passes,12 explicit native skips; independent14 passes. Grades:correctness A-,efficiency A-,DX B+,architecture A. Old local preparation intentionally stopped before any native request; original evidence and bindings retained. Production qualification remains ct-2ukk.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch czsd).
- Grades: proposal 94 → 85, work 91 → 91.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
