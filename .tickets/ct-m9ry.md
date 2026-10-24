---
id: ct-m9ry
status: closed
deps: [ct-2d3k, ct-u7gg, ct-3g69]
links: [ct-d3un, ct-2wsw]
created: 2026-10-19T16:40:42Z
type: task
priority: 1
assignee: mikewolfd
tags: [overlap-followup]
---
# Measure publication Catalog state before choosing a narrower reader

Publication and the identity CLI skip search strings but still construct the general research Catalog tables/maps/membership/facets/API-video state. The retained complete local run reached 5.085 GB highwater during loading and 7.310 GB overall. Establish which live allocations publication actually requires and whether a smaller shared index has a worthwhile payoff. This is a measurement-first followup, not a promise to reduce memory or a prerequisite to manufacture B+ grades.

## Acceptance Criteria

- Use the retained successful receipts first; record required callers and the lifetimes/approximate sizes of projected Arrow tables, source/document maps, memberships and optional viewer state.
- Choose a bounded representative comparison and define its resource ceiling before execution; do not repeat full qualification without a separate need and authorization.
- If evidence supports a narrow shared index, preserve grouping, facets, preferred sources, API/video classification, stable IDs, review member multiset/body checks, resource ownership and all published values.
- Report measured memory, time, scratch and output tradeoffs, or explicitly record why retaining the current model is the better decision.
- Do not call decode admission or the writer buffer budget a total constructor/native-process memory limit; preserve historical successful and failed evidence.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: apps/site/scripts/filename_review_binding.py:72:main, apps/site/scripts/publish-filename-viewer.py:132:publish, docs/youtube-coverage/research/scripts/view_document_filenames.py:270:Catalog.__init__. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data.

**2026-10-19T19:32:51Z**

Completed bounded measurement on merged3757f55 using pinned surviving historical pair (distinct from removed complete-current rollout):30,906 documents/41,030 sources with closed LIST_COLUMNS projection and8 synthetic groups; nested observations typed null. Three fresh constructor samples per arm and actual publisher parity:269 payload hashes + all non-timestamp manifest values identical. Packed positions remove4,926,720 estimated Python bytes but constructor median highwater only249,692,160→246,267,904B; fixture publish361,119,744→349,683,712B,5.4058→5.4796s. Retain current production Catalog; no broad optimization justified by this fixture.52 focused viewer/review tests passed. docs/experiments/efficiency-debt/catalog.md plus exact receipts; leave in_progress for independent review.

**2026-10-19T19:39:00Z**

Independent review accepted 6855f37. All 269 payload hashes and manifest values except publication time match on the bounded historical projection. Packed membership savings do not justify added complexity; production Catalog remains unchanged. Supplemental 52 focused checks pass.

## Audit 2026-10-24

- Verdict: SUPERSEDED (batch standalone).
- Grades: proposal 88 → 80, work 78 → 78.
- Problem: The fixture was 30,906 documents (~2.5%) with nested `source_occurrences` set to null, so the 5.085 GB loading highwater that motivated the ticket stays unattributed (the doc admits this).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:36
- Covered by: WS11 (ct-2wsw).
- See docs/reviews/2026-10-24-ticket-audit/README.md
