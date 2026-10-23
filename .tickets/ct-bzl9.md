---
id: ct-bzl9
status: closed
deps: []
links: [ss-yjut]
created: 2026-10-22T17:45:12Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-syem
tags: [metrics, ast, bloat, dx, docs, smells]
---
# Remediate cross-cutting quantitative AST smells: eliminate >=7-param functions (up to 23 params), raise docstring coverage from 39.6%, and add scripts/dev.py clean for 125 GB local .cache/output bloat

CS300 Audit Finding (Quantitative AST & Static Metrics Auditor - Cross-Repo Summary):

1. **Extreme Parameter Lists (187 Production Python Functions with >=7 Parameters)**:
   - Top AST-verified >=12-parameter production functions in `congressional-tech`:
     - `apps/committee_youtube/src/committee_explorer/export.py:303-965` (`export`, **23 params**)
     - `packages/congress_api/src/congress_api/acquisition/raw_sync.py:78-495` (`run_async`, **19 params**)
     - `packages/congress_api/src/congress_api/cli/raw_sync.py:325-455` (`run`, **18 params**)
     - `packages/congress_api/src/congress_api/retention/document_index.py:2866-3131` (`write_filename_metadata`, **16 params**)
     - `packages/congress_api/src/congress_api/retention/native_features.py:709-793` (`refresh_catalog_join`, **16 params**)
     - `scripts/corpus_recovery/dispatch_corpus_recovery_import.py:338` (`run_batch`, **16 params**)
     - `packages/congress_api/src/congress_api/retention/catalog_scope.py:384-514` (`verify_catalog_scope`, **15 params**)
     - `packages/congress_api/src/congress_api/retention/catalog_updates.py:67-179` (`_update_native_catalog`, **15 params**) & `L42-64` (`update_native_catalog`, **14 params**)
     - `packages/corpus_recovery/src/corpus_recovery/publication.py:71-142` (`publish_imported`, **15 params**)
     - `packages/congress_api/src/congress_api/acquisition/house_sites.py:499-539` (`main`, **15 params**)
     - `packages/viewer_publication/src/viewer_publication/filename_native.py:840-979` (`publish_selected`, **14 params**)
     - `packages/congress_api/src/congress_api/retention/catalog_raw_updates.py:234-543` (`_update_from_raw`, **13 params**)
     - `packages/congress_api/src/congress_api/retention/catalog_publication.py:199-286` (`prepare_native_catalog_chunks`, **13 params**)
     - `packages/congress_api/src/congress_api/retention/raw_storage.py:1039-1228` (`RawStorage.prepare`, **12 params**)

2. **Severe Documentation Debt (60.4% of Public Functions & 63.0% of Classes Missing Docstrings)**:
   - Across 427 non-test Python files in `packages/`, `apps/`, and `scripts/`: **3.3% of modules (14/427)**, **63.0% of classes (323/513)**, and **60.4% of public functions (1,560/2,581)** lack docstrings.
   - Large files (>300 LOC) with **0 `#` comments**: `packages/viewer_publication/src/viewer_publication/filename_exports.py` (1,015 LOC, 11/16 docstrings, 0 `#` comments), `apps/committee_youtube/src/committee_explorer/docspec_views.py` (697 LOC, 17/18 docstrings, 0 `#` comments), `packages/congress_shared/src/congress_shared/custody.py` (436 LOC, 14/14 docstrings, 0 `#` comments).
   - Large files (>300 LOC) with **lowest docstring coverage (<20%)**: `packages/congress_api/src/congress_api/models/house.py` (489 LOC, 2/66 = 3.0% docstrings, 1 `#` comment), `scripts/measure/compare_raw_keyed_updates_scale.py` (376 LOC, 1/18 = 5.6%), `apps/committee_youtube/src/committee_explorer/export.py` (1,006 LOC, 4/25 = 16.0%), `scripts/publication/publish-viewer-r2.py` (585 LOC, 6/35 = 17.1%), `packages/congress_api/src/congress_api/acquisition/raw_sync.py` (495 LOC, 4/22 = 18.2%), `apps/committee_youtube/src/committee_explorer/assemble.py` (1,194 LOC, 11/59 = 18.6%), `packages/congress_api/src/congress_api/models/senate.py` (609 LOC, 9/46 = 19.6%).
   - Longest Production God-Functions: `Extractor.extract` (`house-naming/extraction.py:761`, 740L, no docstring), `export` (`committee_explorer/export.py:303`, 663L, no docstring), `export.assemble_inputs` (`export.py:384`, 426L), `run_async` (`raw_sync.py:78`, 418L, no docstring), `records` (`adapters/senate.py:59`, 388L), `_update_from_raw` (`catalog_raw_updates.py:234`, 310L), `write_filename_metadata` (`document_index.py:2866`, 266L).
   - Largest Completely Uncommented Functions (0 docstring AND 0 `#` comments): `packages/house-naming/tools/compare_filename_engines.py:116-274` (`main`, 159L), `packages/congress_api/src/congress_api/cli/raw_sync.py:325-455` (`run`, 131L), `apps/committee_youtube/src/committee_explorer/coverage.py:11-138` (`build`, 128L), `packages/congress_api/src/congress_api/retention/catalog_rows.py:680-803` (`CatalogRows.read`, 124L), `packages/congress_api/src/congress_api/retention/native_features.py:92-207` (`_compute_field_group_metrics`, 116L), `packages/viewer_publication/src/viewer_publication/filename_exports.py:357-472` (`_publish_occurrence_parquet`, 116L), `packages/news_lake/src/news_lake/storage/docspec_backend.py:1333-1427` (`DocSpecLake._commit_upsert`, 95L); plus 3 functions >200L with a docstring but 0 `#` comments (`export_viewer_pins` at `filename_exports.py:742-1015` 274L, `CatalogDependencyStorage.prepare` at `catalog_dependency_storage.py:518-758` 241L, `DocSpecNewsViews.update_bridges` at `docspec_backend.py:2914-3119` 206L).

3. **125+ GB Local Disk Bloat in `congressional-tech` (and 28.3 GB in `docspec-rs`)**:
   - `.cache/`: 86 GB; `output/`: 39 GB (18,400+ files); `.git/`: 20 GB; `apps/`: 1.5 GB (`apps/site/dist` 742 MB + `apps/site/public` 740 MB = 1.48 GB); `.venv/`: 470 MB; `.playwright-mcp/`: 1.0 MB; `.playwright-cli/`: 168 KB; and 9 stale `*.egg-info` directories + `build/` directories across `packages/` and `apps/`.

4. **Cross-Repo & Cross-Package AST Clones, Single-Occurrence Dead Code & Smells**:
   - 82 `sys.path` manipulations across 76 files; 69 broad `except Exception` blocks across 47 files.
   - Exact AST body clones: `write_bound_receipt` vs `write_atomic_json` (`congress_shared/custody.py:284, 315`, 29L); `resolve_docspec_binary` (`apps/committee_youtube/src/committee_explorer/docspec_views.py:98` vs `packages/congress_api/src/congress_api/retention/weekly_tables.py:203`, 19L); `DocSpecLake._effective_source_table_pin` vs `DocSpecNewsViews._effective_source_table_pin` (`news_lake/storage/docspec_backend.py:950, 2095`, 10L); plus `digest(path)` in 15 files, `encoded(value)` in 6 files, and `version_ref()` in 3 files (`committee_explorer/docspec_views.py:119`, `congress_api/retention/native_features.py:52`, `news_lake/storage/docspec_backend.py:204`).
   - 13 single-occurrence dead Python symbols: `_ValidatedRecords` (`assemble.py:115`), `to_text` (`gpo_text.py:44`), `_legacy_write_document_indexes` (`document_index.py:788`), `_segment` (`transcripts/senate.py:56`), `table_commit_order` (`news_lake/storage/control.py:301`), `_source_parquet_objects` (`docspec_backend.py:113`), `_SpilledSources.meta_for_id` (`assemble.py:276`), `_SpilledRecords.get_compressed_by_key` (`assemble.py:506`), `RawStorage.migrate_pdf_bodies` (`raw_storage.py:697`), `RawStorage.prepare_partitioned_state_table` (`raw_storage.py:947`), `NativeDatasets.update_evidence` (`docspec.py:2165`), `NativeDatasets.read_evidence` (`docspec.py:2381`), `ConditionalManifestPublisher.publish_pointer` (`viewer_publication/client.py:383`).

## Acceptance Criteria

1. Introduce typed configuration/request dataclasses for functions taking >7 parameters (starting with all >=12-parameter functions in `export.py`, `raw_sync.py`, `document_index.py`, `native_features.py`, `catalog_scope.py`, `catalog_updates.py`, `publication.py`, `house_sites.py`, `filename_native.py`, `catalog_raw_updates.py`, `catalog_publication.py`, `raw_storage.py`, and `dispatch_corpus_recovery_import.py`).
2. Add module, class, and public function docstrings to all >300-LOC modules with <20% docstring coverage and inline `#` invariant comments to all >100-LOC functions that currently have 0 `#` comments.
3. Deduplicate the exact AST clones (`write_bound_receipt`/`write_atomic_json`, `resolve_docspec_binary`, `_effective_source_table_pin`, `digest`, `encoded`, `version_ref`) and remove all 13 single-occurrence dead Python symbols.
4. Add a `scripts/dev.py clean` subcommand (and document retention/cache pruning rules) to reclaim stale `build/`, `*.egg-info/`, `output/`, and `.cache/` artifacts.

## Notes

**2026-10-23T01:31:18Z**

User Constraint (Data Preservation): Implement scripts/dev.py clean (--dry-run by default), but do NOT execute destructive deletion of local .cache/ or output/ directories during the run.
