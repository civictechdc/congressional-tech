---
id: ct-qkvr
status: closed
deps: [ct-egpe]
links: [ct-nloa, ct-jo8n, ct-5fkx, ct-ur2y, ct-csyg, ct-xu1o, ct-pgxn, ct-8ax6, ct-r60e, ct-ur7v]
created: 2026-10-20T22:15:53Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Preserve news append history across successive native batches

DocSpecLake._commit_append sends only the new batch as an independent Build. Local Build replaces the current source result; old immutable releases survive but the current view loses prior rows. R2 refuses a later Build. Use an exact-base append/update representation that retains all earlier logical evidence.

## Acceptance Criteria

- First reproduce two distinct polls by reading the actual native result; do not supply merged Python records to hide missing history.
- Preserve append ID uniqueness: identical replay is a no-op and conflicting reuse refuses. Keep old pins readable and source bytes unchanged.
- Bind retry to exact base and content; cover lost replies, interrupted admission, stale writers and coupled relationships (`ct-5fkx`).
- Qualify the supported local and R2 paths; no whole-history read/rewrite in Python (`_existing_by_ids` calling `read_arrow` at `docspec_backend.py:987,1037`) or unbounded $O(\text{files})$ native file probing (`docspec-rs/src/engine/write.rs:606-659`) for a small append. Record changed/reused rows, `files_scanned`, `files_reused`, and bytes across 1, 8, and 32 successive polls.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring / Iceberg / query-plan audit at `main` (`8221566d` / `33ce7877`):
1. `DocSpecLake._commit_append` (`packages/news_lake/src/news_lake/storage/docspec_backend.py:1029-1061`) calls `self._existing_by_ids(prior, kind, ...)` (`:1037`), which calls `self.client.read_arrow(pin, schema=kind_arrow_schema(kind))` (`:987`) and materializes 100% of historical rows and columns (including full `news_versions.text`) into Python memory on every append poll—violating the "no whole-history read/rewrite for a small append" requirement.
2. `_commit_append` (`:1060`) passes `relationship=relationship` to `update_table` (`:924-925`), which sets `spec['relationship']` on `UpdateSpec`; `docspec-rs` silently ignores that field (`src/model.rs:875-883`, `src/engine/inputs.rs:515-528`), breaking `lake.seal()` on Poll 2 (`ct-5fkx`).
3. Each append poll via `UpdateSpec` adds a new Parquet file while keeping prior files in `shared` (`docspec-rs/src/engine/write.rs:606-659`), causing $N$ polls to probe all $N$ prior files ($O(N^2)$ cumulative file probes without Iceberg manifest bounds pruning or compaction).

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: C- (Reopened). Preserves prior poll rows, but _commit_append (docspec_backend.py:1037) calls _existing_by_ids -> read_arrow (:987), materializing 100% of historical rows and text in Python RAM on every append poll, and passes ignored spec['relationship'] to UpdateSpec (ct-5fkx).

**2026-10-21T00:31:41Z**

Nearly closed: the shared transport, exact-base Update, and UpdateSpec relationship support are now implemented. Remaining blocker is _existing_by_ids calling read_arrow (docspec_backend.py:980-997), which still materializes the full historical dataset in Python; track that in ct-nloa/ct-csyg. Also requires the rebuilt binary from ct-oxg6.

**2026-10-21T02:20:25Z**

Implemented and verified: DocSpecLake._commit_append and _existing_by_ids (packages/news_lake/src/news_lake/storage/docspec_backend.py:626-643) now use client.read_keys (/datasets/{dataset}/versions/{version}/keys) so append polls stream only matching IDs (0 rows on new IDs) instead of calling read_arrow on the full table, while replace_keys skips non-overlapping files and advances coupled relationships (ct-5fkx).

**2026-10-21T15:17:45Z**

Scale review 2026-10-21: the docspec-rs replace_keys manifest pruning from 96e3826 had no test and compared each file with the overall affected-key min/max, so it pruned almost nothing. docspec-rs 381108c (spicy-stack ss-6cz9) tests per-file affected key points, with oracle tests. news_lake ids are uuid4 (context.py:88), and random keys give every file a near-total key range, so pruning still decodes every retained file each poll until ct-ur2y (UUIDv7 ids) lands; engine-side alternative in spicy-stack ss-wie5.
