---
id: ct-fsbf
status: closed
deps: []
links: []
created: 2026-10-22T17:43:35Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [congress-api, architecture, bloat, deadcode, duplication, smells]
---
# Break up 82-file (23.6k-LOC) congress_api/retention/ monolith, eliminate 8 circular import cycles & 279 function-local imports, decompose 3,250-LOC document_index.py & 418-LOC raw_sync.run_async, and purge ~1,500 LOC of dead/unwired code

CS300 Audit Finding (Congress API & Shared Auditor):
1. 82-File, 23,613-LOC congress_api/retention/ Monolith & 8 Circular Import Cycles:
   - 56.3% of packages/congress_api (23,613 of 41,924 LOC across 82 files) sits in a single flat retention/ folder to bypass pytest-archon top-level folder rules (pyproject.toml:58-68).
   - Contains 8 direct two-module circular import cycles: (a) catalog_adoption.py <-> catalog_selection.py, (b) catalog_availability.py <-> document_index.py, (c) catalog_batches.py <-> catalog_publication.py, (d) catalog_publication.py <-> catalog_selection.py, (e) catalog_publication.py <-> catalog_validation.py, (f) catalog_publication.py <-> document_index.py, (g) raw_archive.py <-> raw_storage.py, (h) source_replay.py <-> source_update_proof.py — masked by 279 function-local imports (53 inside document_index.py alone).
2. God Modules (>700 LOC) & Monster Functions (>200 LOC):
   - God modules: retention/document_index.py (3,250 LOC, 69 top-level defs/classes incl. 675-line DocumentSources at L1181-1855, BipartiteUnionFind at L447-491, _invert_utf8_hex bitwise sort-key hack at L432-444, global ENGINE at L117, and raw SQLite table drops on WorkingCatalog.connection at L3054-3055), retention/raw_storage.py (1,394 LOC, 35/39 methods missing docstrings), retention/native_features.py (1,270 LOC), parsers/senate_page.py (1,145 LOC), retention/catalog_dependency_storage.py (906 LOC), retention/catalog_rows.py (803 LOC, 0/12 methods have docstrings), retention/raw_archive.py (802 LOC), retention/weekly_tables.py (733 LOC).
   - Monster functions: acquisition/raw_sync.py:78-495 (run_async, 418 LOC, 19 params, 13 nested closures up to 3 levels deep at L342-358, undocumented magic backpressure ratios at L38-39,101,110), adapters/senate.py:59-446 (records, 388 LOC, discards Pydantic SourceModel via prepared_state at L75 to manipulate untyped 3-tuples other[2] at L40,51,103,106), retention/catalog_raw_updates.py:234-543 (_update_from_raw, 310 LOC), retention/document_index.py:2866-3131 (write_filename_metadata, 266 LOC, 14 params, 5 nested closures), retention/catalog_staging.py:331-583 (write_grouped_indexes, 253 LOC), adapters/gpo.py:170-415 (records, 246 LOC), retention/catalog_dependency_storage.py:518-758 (prepare, 241 LOC), retention/document_recovery.py:33-254 (recover_sources, 222 LOC), adapters/house.py:66-278 (records, 213 LOC), parsers/senate_page.py:635-842 (related_page, 208 LOC), acquisition/gpo.py:85-291 (main, 207 LOC), adapters/transcripts.py:48-252 (records, 205 LOC).
3. Dead & Unwired Code (~1,500+ LOC) & Dependency Bloat:
   - Zero callers anywhere (prod or tests): _legacy_write_document_indexes (retention/document_index.py:788-825, 38L), to_text (parsers/gpo_text.py:44-46), _segment (transcripts/senate.py:56-57), adapters/committee_adjustments.py:1-6 shim, RawStorage.migrate_pdf_bodies (raw_storage.py:697), RawStorage.prepare_partitioned_state_table (raw_storage.py:947), and 3 unread CLI flags (--documents-only, --metadata-only, --source-metadata-only) in cli/document_index.py:33-34.
   - Zero production callers: transport/document_probe.py:1-44 & acquisition/documents.py:1-70 (the ONLY files in congress_api importing httpx, forcing httpx>=0.28 into pyproject.toml:13); acquisition/retained_import.py:1-48; acquisition/streamed_recovery.py:1-454 & recovery_queue.py:1-139 (593 LOC); retention/native_capacity.py:138-576 (439 LOC); plus 15 test-only functions in retention/ and parsers/ (document_index.py:2006-2139, 2548-2630, 3225-3240; catalog_cache.py:139-270; catalog_publication.py:347-376; catalog_scope.py:32-74; document_review_bundle.py:24-99; document_review_catalog.py:96-143; meetings.py:101-141; partition_routing.py:19-39; raw_archive.py:117-123; raw_readings_adoption.py:22-25; raw_values.py:38-45; rejected_pages.py:49-77; transcripts.py:57-72; witness_pdf.py:44-50).
4. HTTP/Transport Duplication, CLI Bugs & Smells:
   - 4 HTTP clients (requests, unused httpx, urllib.request.urlopen in transcripts/context.py:119,138 bypassing rate-limiting, and Rust reqwest); duplicated Retry-After parsers (transport/rust_fetch.py:27-49 vs retention/r2.py:57-70); 3x Zyte base64 extraction (transport/zyte.py:1-59, transport/source_capture.py:125-165, source-fetch/main.rs:255-264); duplicated YouTube TinyDB partition readers (retention/tables.py:28-56 vs cli/sync_weekly_tables.py:61-77); private urllib3 traversal in transport/http.py:101-109,159-166 and module-global rate-limit state at L31-40.
   - Missing document-filename-index script in packages/congress_api/pyproject.toml:34-47 (documented in README.md:342,392); CWD-fragile path default in cli/sync_weekly_tables.py:193; empty packages/congress_api/{package.json,turbo.json}; anemic pass-through files (retention/raw_catalog.py:1-26, retention/index_selector.py:1-9, parsers/legislators.py:1-9, parsers/gemini.py:1-11, models/congress_xml.py:1-11, transport/congress.py:1-10).

## Acceptance Criteria

1. Split congress_api/retention/ into layered subpackages (raw/, index/, catalog/, review/) with acyclic pytest-archon rules, breaking all 8 circular import cycles and removing the 279 function-local imports; split document_index.py (3,250 LOC) into focused modules (<700 LOC). 2. Delete dead functions/shims (_legacy_write_document_indexes, to_text, _segment, committee_adjustments.py, migrate_pdf_bodies, prepare_partitioned_state_table, cli/document_index.py:33-34 flags), remove unused httpx dependency + document_probe.py/acquisition/documents.py, and either wire or relocate test-only modules (streamed_recovery.py, recovery_queue.py, retained_import.py, native_capacity.py:138-576). 3. Decompose raw_sync.py:run_async (418 LOC) into composable classes, refactor adapters/{senate,gpo,house,transcripts}.py to preserve typed models instead of raw dicts/3-tuples, deduplicate Retry-After/Zyte/YouTube-partition helpers, register document-filename-index in pyproject.toml, use DEFAULT_CHANNELS_CSV in sync_weekly_tables.py:193, delete empty package.json/turbo.json, and add docstrings to CatalogRows, RawStorage, and run_async.


## Notes

**2026-10-22T17:47:24Z**

Subagent Self-Review Additions (Congress API & Shared Auditor):
1. Broad Exception Swallowing: Narrow the 47 broad except Exception / except BaseException blocks in congress_api, specifically silent swallows in acquisition/raw_sync.py:441-442, retention/native_capacity.py:238-239, and acquisition/gpo.py:177,200,202,231,262.
2. Cross-Module / Cross-Package Encapsulation:
   - Replace working.connection.execute(f'DROP TABLE IF EXISTS {name}') in retention/document_index.py:3054-3055 (dropping tables created in retention/document_recovery.py:92-140) with an explicit method on WorkingCatalog.
   - Expose public read methods on raw_storage, routes, and pages so packages/corpus_recovery/src/corpus_recovery/preservation.py:153,171,185,274,276 stops calling private _read_states/_read internals (and remove the 4-line pass-through shim packages/corpus_recovery/src/corpus_recovery/acknowledge.py:1-4).
3. Anemic Pass-Through File List & Rate-Limiter Duplication:
   - Include retention/docspec_host.py:1-21 (whose private _resolve_docspec_host and _docspec_available functions are re-exported by retention/docspec.py:30-35) alongside the other anemic files.
   - Note rate-limiter duplication between RequestPacer / pace_request (transport/http.py:43-57,125-135) and struct RateLimit (packages/source-fetch/main.rs:28-53).

**2026-10-22T18:33:46Z**

Lead Architect Review (Defend Intent + Compromise):
1. GUARDRAIL ON STAGED MODULES: Distinguish between (a) genuinely obsolete legacy code (_legacy_write_document_indexes in document_index.py:665-720, to_text/_segment in raw_sync.py, stale build/ artifacts, packages/source-fetch/benchmark.rs) which should be deleted immediately, and (b) tested Wave-2C / operator capability modules (acquisition/streamed_recovery.py, recovery_queue.py, retained_import.py, retention/native_capacity.py:138-576) which were built for BWAC streamed recovery and operator capacity inspection. For (b), either wire them into their intended CLI entrypoints or explicitly document/quarantine their staged status rather than blindly deleting tested capability code.
2. CONCEDE: The 82-file retention/ megadirectory, 8 circular imports, and 279 function-local imports bypassing pytest-archon are 100% architectural debt and must be refactored into layered subpackages.

**2026-10-23T01:31:18Z**

User Decision (Staged Modules): Wire ALL staged Wave-2C / operator capability modules (acquisition/streamed_recovery.py, recovery_queue.py, retained_import.py, retention/native_capacity.py:138-576) into their production CLI entrypoints with CLI/integration test coverage as part of this ticket.
