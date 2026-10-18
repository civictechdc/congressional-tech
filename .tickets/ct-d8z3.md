---
id: ct-d8z3
status: open
deps: [ct-x7vx]
links: []
created: 2026-10-18T19:21:16Z
type: epic
priority: 2
assignee: mikewolfd
tags: [publication, audit-20261018]
---
# Improve document publication efficiency and recovery

The function audit found repeated validation, expensive preparation, and recovery gaps across catalog selection, R2 publication, and browser delivery. Preserve exact data, review decisions, and conditional selection while reducing unnecessary work.

Audit: output/publication-exam-20261018/; reviewed code f9f4499.

## Acceptance Criteria

Each linked finding has a verified outcome. Report total successful-build, unchanged-poll, and retry costs separately; do not add unrelated percentage gains.


## Notes

**2026-10-18T19:33:49Z**

Audit complete at f9f4499: 372 graded functions/helpers/entry blocks across 40 files. Report: output/publication-exam-20261018/REPORT.md. Searchable gradebook: output/publication-exam-20261018/gradebook.html. Backlog: output/publication-exam-20261018/BACKLOG.md. Created 24 actionable child tickets with acceptance criteria; dependency graph has 15 edges and no cycles. Static review only; implementation remains open.

**2026-10-18T19:34:22Z**

Final independent review found no material factual errors. Removed the journal-to-instrumentation dependency because it was sequencing rather than a prerequisite; they are linked instead. Final dependency graph: 14 edges, no cycles. Clarified that recovery publication refuses mapping changes made after preparation.

**2026-10-18T19:47:55Z**

Below-B+ follow-up complete: all 168 qualifying function/helper entries reviewed, including 103 with lower overall grades. Added 18 tickets and extended acceptance in 21 existing tickets; 23 existing tickets now link exact function coverage. Current backlog: 42 actionable tickets, 21 dependency edges, no cycles. Coverage: output/publication-exam-20261018/BELOW-B-PLUS.md. Independent readback review found no blockers. Grades and production code are unchanged.

**2026-10-18T21:20:33Z**

All 42 original remediation tickets are closed after implementation in dependency order, independent review, and combined verification. No tickets remain in progress. This epic stays open for ct-x7vx, which requires an ordinary unchanged job after a separately authorized deployment. The report records faster polls and resume, plus a 7.5% increase in fresh-publication time on the small fixture. Local merges only; no rollout.
