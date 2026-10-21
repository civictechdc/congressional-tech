---
id: ct-n6lj
status: open
deps: [ct-jo8n]
links: [ct-gf8i, ct-jo8n, ct-csjp, ct-vt7i]
created: 2026-10-20T23:52:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, views, incremental, efficiency]
---
# Derive incremental news bridge updates from pinned release deltas without full-corpus Python scans

In packages/news_lake/src/news_lake/storage/docspec_backend.py:1190-1272, DocSpecNewsViews.update_bridges requires the caller to pass the full historical corpus in Python (records_or_release_read), recomputes all three bridge tables from scratch in Python (entity_roots_rows, selected_mentions_rows, survivor_items_rows at :1194-1208), and calls self.client.read_arrow(prior_pin) (:1228) to materialize 100% of each prior bridge dataset into Python memory just to diff changed/removed keys. Similarly, _assemble_politician_articles (:1351-1359) requires all version records in Python memory and reads the entire survivor_items dataset via read_arrow.

## Acceptance Criteria

- Compute incremental bridge updates (entity_roots, selected_mentions, survivor_items) from the pinned release/poll delta and affected keys rather than recomputing all historical bridge rows and reading full prior bridge tables via read_arrow in Python (docspec_backend.py:1190-1272).
- Preserve cross-date syndication semantics when a newly arrived survivor item causes an existing text_group_id's corpus count to cross from 1 to >1 (updating both the prior item's identical_text_group_id and the new item's row so incremental coverage_daily refreshes both date buckets).
- Verify hot-group ARRAY_AGG(DISTINCT ...) memory bounds (docspec-rs/src/engine/aggregation.rs:180-185) on a high-cardinality date / NULL undated bucket under production Limits.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to address the CS 300 B- deduction on ct-gf8i: replace full-corpus Python bridge recomputation and full read_arrow bridge diffing in DocSpecNewsViews.update_bridges (docspec_backend.py:1190-1272) and _assemble_politician_articles (:1351-1359) with release-delta keyed updates.
