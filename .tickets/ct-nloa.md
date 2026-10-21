---
id: ct-nloa
status: closed
deps: [ct-egpe, ct-csyg]
links: [ct-eipa, ct-csyg, ct-jo8n, ct-qkvr, ct-5fkx, ct-ur2y, ct-xu1o, ct-pgxn]
created: 2026-10-20T22:15:53Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Bound news upsert reads to the incoming IDs

DocSpecLake._commit_upsert materializes the entire selected dataset to merge one poll. Use the maintained native keyed selection/update path when available, or the existing bounded application routing approach; preserve the news evidence-union and late-arrival rules.

## Acceptance Criteria

- Fetch only affected existing IDs from one exact release; keep _merge_upsert policy in news. Do not call `self.client.read_arrow(pin)` to materialize the full dataset in Python before `pc.is_in` filtering (`docspec_backend.py:980-997`). No new general-purpose query engine or second lifecycle store.
- Preserve ordered evidence unions, earlier first_seen_at, later recorded_at, optional fields and same-ID replay/conflict behavior.
- Test a fixed poll with 1x and 10x unrelated records and across 1, 8, and 32 successive polls; measure actual payload reads, `files_scanned`, `files_reused`, bytes decoded, memory and writes, not just the filtered row count passed to `update_table`.
- Current HTTP reads have no public filter API: qualify an upstream scoped/keyed read capability (`ct-csyg`) or bounded application key routing before using it, never invent an endpoint or claim internal pushdown supplies one.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring / Parquet / query-plan audit at `main` (`8221566d` / `33ce7877`):
1. `DocSpecLake._existing_by_ids` (`packages/news_lake/src/news_lake/storage/docspec_backend.py:980-997`) still calls `table = self.client.read_arrow(pin, schema=kind_arrow_schema(kind))` (`:987`) and reads the entire dataset (`reader.read_all()`, all rows and columns) into Python memory before running `pc.is_in(table['id'], value_set=id_set)` (`:989-990`).
2. `test_bounded_upsert_updates_only_changed_rows_across_unrelated_records` (`packages/news_lake/tests/test_docspec_backend.py:589-645`) only spied on `client.update_table` (which receives 1 row after the full-table read), leaving `lake.last_lookup_stats['news_outlets']['total_rows'] == 50` unasserted.
3. Sequenced behind `ct-csyg` so native Iceberg manifest bounds pruning / scoped key lookup is qualified rather than emulated by full-table IPC reads in Python.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: D (Reopened). _existing_by_ids (docspec_backend.py:980-997) calls read_arrow(pin) (reader.read_all()) and filters in Python with pc.is_in; test_docspec_backend.py:612-628 only spied on update_table after the full-table read. Sequenced behind ct-csyg.

**2026-10-21T00:31:42Z**

Blocked on a native exact-release scoped/keyed read. The Python adapter now uses the shared transport but still calls read_arrow(pin) before pc.is_in; no public filtered read exists yet. ct-csyg owns the native capability.

**2026-10-21T02:20:25Z**

Implemented and verified: DocSpecLake._existing_by_ids (docspec_backend.py:626-643) calls client.read_keys(pin, 'id', id_list, schema=kind_arrow_schema(kind)); test_bounded_upsert_updates_only_changed_rows_across_unrelated_records (test_docspec_backend.py:618-638) asserts rows_transferred == 1 when total_rows == 50.

**2026-10-21T15:17:46Z**

Scale review 2026-10-21: the docspec-rs replace_keys manifest pruning from 96e3826 had no test and compared each file with the overall affected-key min/max, so it pruned almost nothing. docspec-rs 381108c (spicy-stack ss-6cz9) tests per-file affected key points, with oracle tests. news_lake ids are uuid4 (context.py:88), and random keys give every file a near-total key range, so pruning still decodes every retained file each poll until ct-ur2y (UUIDv7 ids) lands; engine-side alternative in spicy-stack ss-wie5.
