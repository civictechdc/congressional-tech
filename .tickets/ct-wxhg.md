---
id: ct-wxhg
status: closed
deps: []
links: []
created: 2026-10-22T17:45:12Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [viewer-publication, corpus-recovery, deadcode, performance, bloat, dx, smells]
---
# Purge 1,500+ LOC of dead code in viewer_publication & corpus_recovery, replace inspect.getsource() hashing in native_requirements, and fix per-URL SQLite/pickle bottleneck in CatalogRecoverySources.at_url

CS300 Audit Finding (Corpus, Viewer & News Lake Auditor - viewer_publication & corpus_recovery):
1. ~1,500+ Lines of Dead Code Across viewer_publication & corpus_recovery:
   - packages/viewer_publication/src/viewer_publication/filename_exports.py:99-287, 475-1016 (~750 lines): 14 export-pin builder functions (_arrow_schema_to_export_fields, visible_reading_fields, build_source_export_policy, build_component_export_policy, build_source_export_spec, build_component_export_spec, compute_browse_ranges, compute_facet_entries, fold_source_readings_table, build_export_pin_descriptor, _sort_sources_table, _sort_components_table, _build_child_table_export, export_viewer_pins) have 0 production callers and discard parameters via _ = destination_dir (L147, 197, 241, 273, 477, 511, 641). Only publish_occurrence_parquet (L290-472) is used in prod.
   - packages/viewer_publication/src/viewer_publication/client.py:266-391 (126 lines): publish_manifest_pointer and ConditionalManifestPublisher have 0 prod callers.
   - packages/viewer_publication/src/viewer_publication/filename_navigation.py:1-139 (139 lines) & scripts/publication/publish-filename-viewer.py:42-165 (verify, fetch, write_u32, repack_and_verify) + ~800 lines of retired v5 viewer branches in filename_viewer.py:275-766, filename_review_binding.py:59-85, filename_recoveries.py:1-90, filename_alias_index.py:1-170, publish-viewer-r2.py, and verify.py:165-176.
   - packages/corpus_recovery/src/corpus_recovery/preservation.py:1-328 (328 lines, 0 prod callers; verify_legacy at L20-53, 78-136 targets retired baseline/indexes/captures.parquet) and packages/corpus_recovery/src/corpus_recovery/inventory.py:139-316 (scan_receipt_history, 178 lines, 0 prod callers).
   - Micro-file wrappers: corpus_recovery/acknowledge.py (4L), scripts/corpus_recovery/reconcile_corpus_recovery_bodies.py (12L), viewer_publication/filename_compression.py (12L), filename_resources.py (17L), filename_aliases.py (29L, unused wrapped_target import at L3).
2. Severe DX Trap in native_requirements() (packages/viewer_publication/src/viewer_publication/filename_native.py:714-731):
   - Hashes inspect.getsource(...) of 9 Python classes/functions and raw file bytes of 7 .py files (filename_Native_recoveries.py, filename_observations.py, filename_details.py, filename_browse.py, filename_search.py, filename_viewer.py, viewer_release_identity.py). Editing any comment, docstring, type annotation, or formatting in those 7 files raises ValueError('Viewer rendering requirements changed without explicit --renderer-upgrade') (filename_renderer_state.py:46-47)!
3. Per-URL Tempdir + SQLite + Pickle Bottleneck in CatalogRecoverySources.at_url (packages/viewer_publication/src/viewer_publication/filename_native_recoveries.py:31-42):
   - On every uncached URL lookup, at_url(url) creates a tempfile.TemporaryDirectory on disk, opens a new SQLite database (entries.sqlite), pickle.dumps each matching row into a BLOB just to run SELECT payload FROM rows ORDER BY source_id, and pickle.loads them back!
4. Duplication, Positional 4-Tuple Obsession & Missing Documentation:
   - SHA-256 digest(path) copy-pasted 10x across corpus_recovery & viewer_publication (admission.py:24, guards.py:70, inventory.py:33, dispatch_corpus_recovery_import.py:23, dispatch_corpus_recovery_publication.py:113, prepare_corpus_recovery_source_records.py:31, run_corpus_recovery.py:25, continuation.py:18, publish-filename-viewer.py:37, publish-viewer-r2.py:54) and canonical JSON encoded(value) copy-pasted 5x (continuation.py:14, local.py:21, reconciliation.py:19, publish-viewer-r2.py:50, viewer_release_identity.py:16) instead of using congress_shared.custody.
   - Batch manifest verification duplicated 3x in corpus_recovery (admission.py:29-88, inventory.py:44-84, transfer.py:143-173) and rclone.conf parsing duplicated 4x (transfer.py:59-72, guards.py:43-59, run_corpus_recovery.py:40-53, dispatch_corpus_recovery_publication.py:98-110).
   - ProtectedIdentity 4-tuples indexed positionally as record[0], record[3], record[:2], read_identity(...)[:3] across publish-viewer-r2.py:65-69, 103, 134, 269, 321 and viewer_publication/attempt.py:61-63, 98-99, 106, 173, 317-319.
   - NativeComponents (filename_native.py:426-694, 269 lines of SQLite + >III binary struct packing), filename_renderer_state.py:1-115, and assemble_corpus_recovery (admission.py:99-243) have virtually zero docstrings or comments.

## Acceptance Criteria

1. Delete the ~750 lines of unused export-pin functions in filename_exports.py:99-287, 475-1016, ConditionalManifestPublisher & publish_manifest_pointer in client.py:266-391, verify_legacy in corpus_recovery/preservation.py:20-53, 78-136, and scan_receipt_history in corpus_recovery/inventory.py:139-316; relocate retired v5 helpers (filename_navigation.py, publish-filename-viewer.py:42-165) to test helpers. 2. Replace inspect.getsource() and raw .py file hashing in filename_native.py:714-731 (native_requirements) with an explicit semantic RENDERER_VERSION constant so comment/docstring/formatting edits do not invalidate viewer builds. 3. Replace the TemporaryDirectory + SQLite + pickle.dumps sort in CatalogRecoverySources.at_url (filename_native_recoveries.py:31-42) with in-memory Python sorting (rows.sort(key=lambda r: str(r.get('source_id') or ''))). 4. Replace the 10 duplicate digest(path) and 5 duplicate encoded(value) helpers with congress_shared.custody, unify batch manifest verification and rclone.conf parsing in corpus_recovery, use typed ProtectedIdentity attributes instead of positional tuple indexing, and document NativeComponents (filename_native.py:426-694), filename_renderer_state.py, and assemble_corpus_recovery.


## Notes

**2026-10-22T17:47:24Z**

Subagent Self-Review Additions (Corpus, Viewer & News Lake Auditor):
1. Architectural Layering Inversion (cross-linked with ct-unv0):
   - packages/viewer_publication/src/viewer_publication/attempt.py:27-35 and verify.py:27-37 dynamically load scripts/publication/publish-viewer-r2.py and publish-filename-viewer.py via importlib.util.spec_from_file_location, while scripts/publication_preflight.py:44-54 uses ast.parse on publish-viewer-r2.py to extract PROTECTED_OUTCOMES and PROTECTED_SURFACES. Move these into packages/viewer_publication so scripts import from viewer_publication.
2. PEP 8 Minification / Semicolon-Packing:
   - Format scripts/publication_preflight.py:1-130, scripts/viewer_release_identity.py:1-118, packages/viewer_publication/src/viewer_publication/verify.py:1-214, filename_renderer_state.py:1-115, scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:21-95, and packages/corpus_recovery/src/corpus_recovery/admission.py:72-96 with ruff format.
3. Remaining Dead Helpers, Unused Imports & Outdated README:
   - Delete dead helpers/imports: packages/viewer_publication/src/viewer_publication/attempt.py:390-405 (_require_object, _require_string, _optional_string), packages/corpus_recovery/src/corpus_recovery/transfer.py:86-98 (stage_local_copy), scripts/publication/publish-filename-viewer.py:17 (unused shutil), and scripts/publication/publish-viewer-r2.py:14-15 (unused shutil, subprocess).
   - Update packages/viewer_publication/README.md:1-19 to document the 24 filename_*.py modules (and note casing fix: filename_native_recoveries.py).

**2026-10-22T18:33:46Z**

Lead Architect Review (Defend Intent + Compromise):
1. DEFEND + REFACTOR: CatalogRecoverySources.at_url(url) in filename_native_recoveries.py:31-42 uses SQLite on disk for a real reason: prolific/malformed URLs in the historical corpus can have tens of thousands of observations, and sorting them all in a Python list in RAM would violate the strict max_ordered_bytes memory budget (tested in test_filename_decoded_budget.py). However, creating a new TemporaryDirectory + CREATE TABLE on every single URL (even 1-5 row URLs) is bad I/O design. Fix by sorting in memory when below a row/byte threshold (e.g. <256 rows / 64 KiB) and reusing a single SQLite temp connection when spilling above the threshold.
2. DEFEND + REFACTOR: native_requirements() in filename_native.py:714-731 hashes source code to prevent silent stale-cache reuse during incremental viewer runs when renderer logic changes without a manual version bump. To avoid invalidating caches on comment/formatting edits without losing automatic change detection, hash normalized AST (ast.dump(ast.parse(source)) with docstrings stripped) or pair an explicit RENDERER_VERSION constant with a unit test that asserts the version is bumped when AST changes.
3. GUARDRAIL ON DEAD CODE: Before deleting export_viewer_pins (filename_exports.py:553-813) and ConditionalManifestPublisher (client.py:266-391), verify whether they should be wired into the C5 native export/publish CLI workflow or removed. Definitely delete obsolete legacy code (verify_legacy, filename_navigation.py, retired v5 branches, unused _ = destination_dir params).

**2026-10-23T01:31:18Z**

User Decision (Staged Modules): Wire ALL staged C5 export/publish modules (filename_exports.py:export_viewer_pins, build_source_export_policy, and client.py:ConditionalManifestPublisher) into their production CLI entrypoints with CLI/integration test coverage as part of this ticket.
