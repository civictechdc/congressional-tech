---
id: ct-m9ry
status: open
deps: [ct-2d3k, ct-u7gg, ct-3g69]
links: [ct-d3un]
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
