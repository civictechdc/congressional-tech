---
id: ct-0bce
status: open
deps: []
links: [ct-d8cf, ct-r6xw]
created: 2026-10-22T17:45:12Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [news-lake, architecture, bloat, duplication, deadcode, smells]
---
# Decompose 3,928-LOC news_lake/storage/docspec_backend.py, deduplicate compaction & release state machines, and remove dead code & schema duplicates

CS300 Audit Finding (Corpus, Viewer & News Lake Auditor - packages/news_lake):
1. 3,928-LOC God-Module (packages/news_lake/src/news_lake/storage/docspec_backend.py:1-3928):
   - Combines 7 layers in one file: JSON-Schema-to-Arrow compiler (L226-303), C1 upsert merge spec compiler (L305-344), C5 SQL-AST expression builder (L346-491), RPC/CLI transport wrapper DocSpecClient (L498-762), storage commit/compaction/release coordinator DocSpecLake (L764-1865), incremental materialized-view delta engine DocSpecNewsViews (L1912-3717), and C5 file exporter (L3720-3901).
   - Retains dual legacy/modern implementations for pre-ss-65bz/ss-6gwu binaries despite QUALIFIED_DOCSPEC_RUNTIME pinning: DocSpecLake._commit_upsert (L1333-1427), DocSpecNewsViews.politician_articles (L3132-3172, 3284-3520), DocSpecNewsViews.coverage_daily (L3576-3716), and DocSpecNewsViews.export_authorized (L3731-3900).
   - Law of Demeter & Encapsulation violations: getattr(self.client._native, 'remote', None) (L912, 977, 2062, 2118) and repeated 5-level dict train-wrecks pin.get('dataset', {}).get('groups', {}).get('source', {}).get('metadata', {}).get('path') (L1007-1121, 1449, 1472-1473, 1705-1716, 2268-2277).
2. Severe Internal & Cross-Module Duplication in news_lake:
   - ~200 lines of compaction & pin-state methods copy-pasted verbatim between DocSpecLake (L837-1079) and DocSpecNewsViews (L1987-2215): _load_committed_state/_load_views_state, _save_committed_state/_save_views_state, compact_lifecycle, _effective_source_table_pin, active_parquet_files, compact_table, compact_tables, _maybe_compact_table, _operation.
   - ~350 lines of release state machine methods duplicated via hasattr duck-typing between releases.py/coordinator.py and docspec_backend.py: build_release (releases.py:59-78 vs docspec_backend.py:1460-1485), publish_release (releases.py:183-288 vs docspec_backend.py:1487-1607), abandon_cycle (coordinator.py:264-351 vs docspec_backend.py:1609-1779), read_release (releases.py:306-365 vs docspec_backend.py:1791-1864).
   - Survivor resolution, run selection, and bridge derivation triplicated across analysis/selection.py:69-81, analysis/views.py:17-127, analysis/bridges.py:140-416, and docspec_backend.py:1872-1910, 2512-3120 (608 uncommented lines of incremental bridge delta propagation).
   - packages/news_lake/docs/checks/validate.py:40-142 duplicates contract/semantics.py:13-220; packages/news_lake/docs/schema/news-lake.schema.json (512 lines) is a duplicate copy of src/news_lake/contract/schema/news-lake.schema.json.
3. Dead Code & Smells in news_lake:
   - Unused imports in docspec_backend.py:38, 40, 45, 47, 48-50, 76, 78 (ipaddress, math, stat, tempfile, urllib.error, quote, urlsplit, urllib.request, build_export_spec, cleanup_safe); dead _source_parquet_objects (docspec_backend.py:113-118); no-op @contextmanager DocSpecClient.serve (docspec_backend.py:531-534); dead table_commit_order (storage/control.py:301-303); dead table_for_kind and mutation_for_table (contract/records.py:138-149); dead BRIDGE_KEYS and BRIDGE_SCHEMAS (analysis/bridges.py:57-67).
   - Unbounded memory materialization in Lake.read_table (storage/tables.py:136-138: scan.to_arrow().to_pylist()) and Views._load (analysis/views.py:41-52); 8-12 parameter signatures in Coordinator.run_cycle (storage/coordinator.py:50-124), commit_poll_batch (storage/commits.py:57-68), and publish_release (storage/releases.py:183-193); broad except Exception in docspec_backend.py:920, 1025, 1666, 2070, 2162; outdated packages/news_lake/README.md:5-47 (references deleted docs/SPEC.md and omits docspec_backend.py).

## Acceptance Criteria

1. Split docspec_backend.py (3,928 LOC) into a subpackage news_lake/storage/docspec/ (schema.py, client.py, compaction.py, lake.py, views.py, incremental.py, export.py) and retire legacy pre-ss-65bz/ss-6gwu fallback branches. 2. Extract a shared _DocSpecDatasetManager base class/mixin eliminating the ~200 lines of duplicated compaction/state methods between DocSpecLake and DocSpecNewsViews, and unify the release publication/abandonment/read state machine in releases.py and coordinator.py over a storage Protocol (~350 lines saved). 3. Deduplicate survivor/mention/bridge resolution across views.py, bridges.py, and docspec_backend.py, deduplicate docs/checks/validate.py and docs/schema/news-lake.schema.json, delete all dead functions/constants/imports, and document the incremental bridge delta propagation algorithm (docspec_backend.py:2512-3120) and README.md.


## Notes

**2026-10-22T17:47:24Z**

Subagent Self-Review Additions (Corpus, Viewer & News Lake Auditor):
1. Silent Exception Swallowing in ObjectStore & Per-Row RPC Loop:
   - packages/news_lake/src/news_lake/storage/control.py:115, 134, 152, 179, 250, 272: except Exception: return False in ObjectStore.exists and list_keys silently masks transient S3/R2 network/auth failures as 'object does not exist'.
   - packages/news_lake/src/news_lake/storage/docspec_backend.py:1318: commit_table loops 'for row in rows:' calling self.client.upsert(...) per row instead of batching via upsert_many.
2. Acceptance Criteria Additions:
   - Replace 5-level nested pin dictionary train-wrecks (docspec_backend.py:1007-1121, 1449, 1472-1473, 1705-1716, 2268-2277) with a typed helper, replace the 8-12 parameter signatures in Coordinator.run_cycle / commit_poll_batch / publish_release with a typed context dataclass, and narrow except Exception in control.py and docspec_backend.py.

## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 77 → 77, work 69 → 69.
- Problem: The commit title's "unify releases" is false. `docspec_backend.py` remains as an 86-line re-export shim that production code still imports (`cli.py:26`, `storage/__init__.py:10`).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:83
- Status: Reopened. Unmet: AC2, one release state machine (`releases.py`/`coordinator.py` still dispatch by `hasattr`); WS8 (ct-d8cf) deletes the PyIceberg backend, the dispatch and the `docspec_backend.py` shim. AC1 (retire the `chained=False` and `two_stage_syndication=False` branches and the ignored `native_upsert_merge` flag) is not a named plan step; WS8 should remove them with the backend.
- See docs/reviews/2026-10-24-ticket-audit/README.md
