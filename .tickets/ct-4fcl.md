---
id: ct-4fcl
status: open
deps: []
links: [ct-tw3r, ct-r6xw]
created: 2026-10-22T17:36:18Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [docspec, architecture, deadcode, duplication, dx]
---
# Decompose 2,629-LOC docspec.py god-module, remove leaked domain policy, finish congress_api shim migration, and add type annotations

CS300 Audit Finding (DocSpec Client & Boundary Auditor):
1. 2,629-Line (116 KB) God Module & Leaked Domain Policy: packages/docspec_client/src/docspec_client/docspec.py bundles 8 layers (pure-Python BLAKE3 L56-158, spec builders, Python relational merge engine L419-603, Arrow schema translation L786-959, producer Parquet staging, export DSL compiler L1127-1544, ELF/Mach-O binary verification L1558-1761, and 54 NativeDatasets methods L1763-2628). Despite __init__.py:4-5 claiming 'no congressional-tech domain policy', docspec.py hardcodes 'count_non_null' SQL synthesis (L1152-1157), 'source_occurrences' / 'source_id' / 'owner_id' / 'occurrence_order' / 'occurrence_is_null' (L1263-1285), and default columns ['source_id'] (L1348).
2. Intra-File & Cross-Package Duplication: (a) Two competing UpdateMergeSpec implementations in the same file (class UpdateMergeSpec(dict) at L357-416 vs build_update_merge_spec at L962-993, where the latter accepts list/tuple order_by that Rust rejects); (b) two SortColumn normalizers (L647-660 vs L1127-1140); (c) 5x duplicated version_ref normalizers (docspec.py:161, 1380; news_lake/docspec_backend.py:204; congress_api/retention/native_features.py:52; committee_explorer/docspec_views.py:119); (d) 3x copy-pasted 45-line producer staging blocks (run_table L1894-1950, update_table L2042-2123, update_evidence_table L2171-2228); (e) 4x copy-pasted Arrow stream readers; (f) 265-line 1:1 pass-through wrapper DocSpecClient in packages/news_lake/src/news_lake/storage/docspec_backend.py:498-762.
3. Dead Code & Half-Migrated Shims: (a) Re-export shims packages/congress_api/src/congress_api/retention/docspec.py and docspec_host.py are still imported by 8 congress_api modules and tests/test_docspec_*.py; (b) 15+ dead exports/methods (ARROW_STREAM_MIME, VALID_UPDATE_MERGE_STRATEGIES, SUPPORTED_PLATFORMS, PRODUCER_PARQUET_ROW_GROUP_SIZE, producer_input_entry, UpdateMergeSpec.latest_or_backfill, NativeDatasets.read_evidence, NativeDatasets.update_evidence, NativeDatasets.export_table, dead 415/unknown-field fallbacks at L1890-1924 & L2038-2100); (c) ignored destination param in build_export_spec (L1434) and no-op if facet_set is not None: return by_column; return by_column in facet_summary (L1542-1544); (d) unused stdlib imports in news_lake/storage/docspec_backend.py:38,45,48-50.
4. DX, Typing & Smells: Zero type annotations across 2,933 LOC; dict-subclassing anti-pattern; CQS violation self.last_evidence_plan = plan (L2203); ' ordinal_column'.strip() (L1277); fabricated zero-digest manifest in _resolve_version_ref (L1397-1421); spawning subprocess docspec hash + re-hashing binary on every staged call (L1767, 1840); 3 incompatible binary discovery helpers across packages.

## Acceptance Criteria

1. Split docspec.py into focused typed modules (host.py, specs.py, schema.py, export_policy.py, client.py) and move congressional-tech domain defaults ('source_occurrences', 'source_id', 'count_non_null') out of docspec_client. 2. Consolidate UpdateMergeSpec, SortColumn, VersionRef, _stage_producer_request, and _stream_verified_pin; collapse news_lake's pass-through DocSpecClient wrapper. 3. Complete migration off congress_api.retention.docspec* shims and remove all dead exports/methods/params (destination, facet_set placebo, export_table, read_evidence, update_evidence, unused imports in docspec_backend.py). 4. Add type annotations, provide one canonical resolve_docspec_binary helper, and document BLAKE3, Arrow IPC EOS framing, __docspec_supplied_* stripping, and x-docspec-spec-base64 headers.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
1. Item 2(f) (news_lake DocSpecClient wrapper, docspec_backend.py:498-762): Explicitly cite DocSpecClient.try_latest (docspec_backend.py:553-559) re-implementing NativeDatasets.try_latest (docspec.py:2524-2530), and DocSpecClient.source_batches / read_arrow / read_keys (docspec_backend.py:626-673) passing schema=None to self._native only to call restore_application_schema manually.
2. Item 3(b) (Dead methods): Also list NativeDatasets.plan_update (docspec.py:2518-2519, 0 prod calls) and the 4 redundant .to_dict() methods on dict subclasses (PartitionTransformSpec.to_dict at L250-251, PartitionFieldSpec.to_dict at L302-303, UpdateMergeSpec.to_dict at L415-416, ConnectedComponentsTransform.to_dict at L782-783).
3. Item 4 (DX & DocSpecFailure cleanup): Replace the fake subprocess.CompletedProcess([], response.status_code, stderr=diagnostic) wrapper on HTTP responses (docspec_host.py:204-205) and dual .status / .status_code properties (docspec_host.py:29, 40-46, worked around via getattr(error, 'status', None) or getattr(error, 'status_code', None) at docspec.py:1891, 2039) with a clean typed exception hierarchy aligned with docspec_dagster/client.py:34-59.

**2026-10-22T18:33:46Z**

Lead Architect Review (Defend Intent + Compromise):
1. DEFEND: In packages/docspec_client/src/docspec_client/docspec.py, NativeDatasets methods read_evidence, update_evidence, export_table, and plan_update are public 1:1 SDK bindings for the docspec-rs HTTP API (/evidence, /exports, /updates/plan) and are covered by cross-repo integration tests. Do NOT delete supported engine endpoint methods from the client SDK just because a downstream app hasn't wired every endpoint yet; DO split docspec.py into focused submodules (models, transport, host, client) and delete genuinely dead private helpers (_retired_value, _merge_cleanup, _json_bytes).

**2026-10-22T18:41:53Z**

CS300 Subagent Sign-Off (e53d5741): Verified read_evidence, update_evidence, and plan_update map 1:1 to active routes in docspec-rs/src/http.rs (L44, L47, L156-157) and export_table provides keyword-arg symmetry; defense accepted. Implementation refinement: have export(request, ...) delegate to self.export_table(request, ...) when isinstance(request, str) to deduplicate the 10-arg build_export_spec call.

## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 72 → 72, work 65 → 65.
- Problem: The split created two new re-export shims, `docspec_client/docspec.py` and `docspec_host.py`, and `__init__.py:7,41` imports through them.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:86
- Status: Reopened. Unmet: AC2, the triplicated producer staging (WS3 step 2, ct-tw3r), and AC3, production imports of the `congress_api.retention.docspec` shims plus the two new `docspec_client` shims (WS10, ct-r6xw). AC1 (domain policy in docspec_client) and AC4 (docstrings) are not carried.
- See docs/reviews/2026-10-24-ticket-audit/README.md
