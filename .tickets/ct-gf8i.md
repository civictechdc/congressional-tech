---
id: ct-gf8i
status: closed
deps: [ct-jo8n, ct-n6lj]
links: [ct-csjp, ct-vt7i, ct-gziq, ct-n6lj, ct-jo8n]
created: 2026-10-20T22:15:53Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Adopt typed native news joins and incremental coverage summaries

News already uses native Date32 grouping and CountDistinct. Finish the remaining view work: typed occurrence spans instead of JSON, changed bridge rows instead of full rematerialization, and native repeated-text group membership using qualified deterministic set aggregation.

## Acceptance Criteria

- Use list<struct> mention occurrences end to end; compare Unicode offsets, span merging, null/empty/duplicate values and nested exports against the current domain reference.
- Update only changed entity_roots, selected_mentions and survivor_items, then Refresh against exact old/new inputs. Preserve identity decisions, selected runs, survivor rules and join cardinality.
- Coverage must list groups repeated across distinct item IDs anywhere in the corpus, then associate them with each date bucket; preserve cross-date syndication, same-item duplicates, undated buckets and sorted output. A per-day CollectSet alone is wrong.
- Native 22a804e includes CollectSet in local Refresh, producing sorted unique non-null lists. Verify this operation on the intended backend; remove JSON conversion and the second full Python survivor scan only after full/incremental parity and hot-group resource checks.
- Measure bridge rows rebuilt, payload read/written and aggregate memory/spill; existing CountDistinct/Date32 use is not a new adoption claim.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring / query-plan audit at `main` (`8221566d` / `33ce7877`):
1. Commit `33ce7877` landed `list<struct>` `occurrences` in `selected_mentions` / `politician_articles`, `AggregateFunction::CollectSet` (`collect_set`) over `identical_text_group_id` in `coverage_daily` (`bridges.py:38,130-169`, `docspec_backend.py:1379-1382,1424-1427`), and `DocSpecNewsViews.update_bridges` (`docspec_backend.py:1190-1272`).
2. Remaining open gaps in `ct-gf8i`:
   - `update_bridges` (`docspec_backend.py:1192-1237`) still requires the caller to pass the full in-memory corpus `records`, recomputes all three bridge tables from scratch in Python (`entity_roots_rows`, `selected_mentions_rows`, `survivor_items_rows`), and calls `self.client.read_arrow(prior_pin)` (`:1228`) to read 100% of each prior bridge table into Python memory for diffing.
   - `_assemble_politician_articles` (`docspec_backend.py:1351-1359`) still requires all `version` records in memory (`_by_kind(list(records), 'version')`) and reads the entire `survivor_items` table into Python (`self.client.read_arrow(survivor_pin)`).
   - Incremental cross-date syndication test coverage is needed where Poll 1 admits item A on day $D_1$ (`identical_text_group_id = None`) and Poll 2 admits syndicated item B with identical text on day $D_2$, verifying that incremental `survivor_items` update transitions item A's `identical_text_group_id` from `None` to `group_id` and incremental `coverage_daily` refreshes both $D_1$ and $D_2$.
   - Hot-group `ARRAY_AGG(DISTINCT ...)` memory bounds (`docspec-rs/src/engine/aggregation.rs:180-185`) must be measured on a high-cardinality date / `NULL` undated bucket under production `Limits`.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: B- (Reopened). Native list<struct> occurrences and CollectSet in coverage_daily work well, but incremental bridge derivation without full-corpus Python scans is tracked in ct-n6lj.

**2026-10-21T00:31:41Z**

Semantic cross-date syndication is already covered: test_update_bridges_pin_isolation_and_cross_day_syndication asserts both 2026-10-18 and 2026-10-19 buckets carry the shared text_group_key. Remaining scope is efficiency only, tracked in ct-n6lj.

**2026-10-21T02:20:25Z**

Implemented and verified: list<struct> occurrences, native CollectSet in coverage_daily, release-pinned incremental bridge updates (ct-n6lj), and projected read_keys lookup in _assemble_politician_articles all pass in test_docspec_backend.py (14 passed).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 86 → 86, work 80 → 80.
- Problem: The AC to measure payload read/written and aggregate memory/spill is met only through `last_bridge_diff` counters and the hot-group receipt.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:35
- Covered by: WS8 (ct-d8cf).
- See docs/reviews/2026-10-24-ticket-audit/README.md
