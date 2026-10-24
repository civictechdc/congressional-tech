---
id: ct-sbdp
status: closed
deps: []
links: [ct-uov2]
created: 2026-10-22T17:36:18Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [tests, scripts, duplication, bloat, hygiene, smells]
---
# Relocate 213 congress_api root tests, eliminate 200+ cross-test imports & semicolon golf, and deduplicate sha256/batch/lock helpers across scripts & packages

CS300 Audit Finding (Scripts, Root Tests & DX Auditor):
1. Root tests/ Sprawl (230 files) & Cross-Test Import Web: 213 of 219 test_*.py files in root tests/ test congress_api (while packages/congress_api/tests/ has only 13 files), and packages/viewer_publication/tests/ prepend ROOT / 'tests' to sys.path to import from root test_*.py files. Over 200 statements across tests/ import test doubles directly from other test_*.py files (e.g. from test_raw_source_sync import MemoryStore), and test doubles are redefined dozens of times (class Client 13x, Handler 11x, Remote 10x, Store 9x). tests/test_native_features.py is 1,349 lines.
2. Duplicated Utilities & Guards Across scripts/ and packages/:
   - digest(path) SHA-256 helper re-implemented 15+ times across corpus_recovery, scripts/corpus_recovery, scripts/publication, and scripts/measure.
   - 3 divergent JSON save() helpers and 3 now() helpers in scripts/webharvest/.
   - Batch manifest & readiness verification triplicated in scripts/corpus_recovery/dispatch_corpus_recovery_import.py:32-58, corpus_recovery/inventory.py:97-136, and corpus_recovery/admission.py:84-120.
   - Local recovery flock, local_check, protected_check, and ~/.R2_config boto3 setup duplicated across dispatch_corpus_recovery_import.py:81-177, dispatch_corpus_recovery_publication.py:189-285, and scripts/publication/*.py.
   - Control-plane pointer verification triplicated across publication_preflight.py:131-181, publish-viewer-r2.py:553-577, and viewer_publication/verify.py:142-174.
3. Dead v5 Viewer Code & One-Off Scripts: Retired CLI stub in publish-filename-viewer.py:180-181 and dead v5 branches in publish-viewer-r2.py:199-230, 373-394 and viewer_publication/verify.py:35-61; one-off historical scripts incremental_boundary_proof.py, probe_corpus_recovery_memory.py, measure_alias_preparation.py, measure_preparation_resources.py, measure_catalog_partition_reuse.py, and unreferenced tests/docspec_transport_measure.py; empty turbo.json tasks and .gitignore:377 typo (!apps/website/src/lib/).
4. Code Smells: Semicolon golf & stripped whitespace in publication_preflight.py, viewer_release_identity.py, viewer_publication/verify.py, test_publication_preflight.py, and generator .throw() lambdas in test_publication_cli.py:39-46; 21 inline __import__(...) expressions in tests; runtime exec(compile(...)) + unbounded _CACHE_LOCKS in webharvest_validation.py:14, 100-101, 167-173; global monkey-patching without finally cleanup in docspec_transport_measure.py:54-65; Host.__new__(Host) in docspec_transport_helpers.py:8.

## Acceptance Criteria

1. Extract shared test doubles (MemoryStore, SelectorStore, MemoryNative, FakeR2Remote) into conftest.py / testing_fakes.py, eliminate cross-test imports from test_*.py, and organize congress_api tests under packages/congress_api/tests/. 2. Centralize file_sha256, atomic JSON save, and R2 client config in congress_shared, and unify batch readiness/lock/preflight checks in corpus_recovery and viewer_publication. 3. Remove retired v5 viewer code, archive one-off historical scripts, fix .gitignore:377 and scripts/measure/README.md, replace exec(compile(...)) + unbounded _CACHE_LOCKS in webharvest_validation.py with bounded cached module loading, and format Semicolon-golfed files with ruff format while replacing inline __import__(...) with top-level imports.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
1. Repository & Disk Bloat:
   - .tickets/ git bloat: 193 closed .tickets/*.md files (~876 KB) committed to git.
   - docs/ git bloat (29 MB): 121 one-off dated JSON receipts in docs/recovery/*-20261016.json (728 KB), 69 .py files across docs/experiments/* (8.6 MB), and 39 .py files + a 4.0 MB CSV (docs/youtube-coverage/hearing_video_verdicts.csv) in docs/youtube-coverage/ (18 MB).
   - output/ local sprawl (39 GB, 18,400+ files): Contains untracked ad-hoc .py scripts (output/r2-survey-20261019/{inventory.py, cloudflare_metadata.py, compare_inventory.py, document-comparison/*.py}) and .v1/.v2 backup files; add a scripts/dev.py clean command or retention policy.
   - Workspace config mismatch (package.json:6, turbo.json:1-5, README.md:11-26): package.json:6 declares 'workspaces': ['apps/*', 'packages/*'] even though packages/* are Python packages, and README.md:11 claims an active Turborepo build pipeline while turbo.json:1-5 has 'tasks': {}.
2. Additional Code Smell & Uncommented Code Citations:
   - scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:33-57 (SelectedRuntime): Mutates sys.path[:] and purges sys.modules in-process to load an external checkout (replace with subprocess isolation).
   - scripts/measure/measure_publication_control.py:142-143: Mutates private module cache (sys.modules.get('viewer_release_identity')._source_cache.clear()).
   - tests/test_catalog_pair_validation.py:21-71: Mixes unittest.TestCase + if __name__ == '__main__': unittest.main() (line 71) with pytest functions (lines 74-231) and mutates function bytecode (original.__code__ = changed.__code__ at line 60).
   - Uncommented binary/control-plane protocols: Document scripts/measure/viewer_benchmark_server.py:83-97 (<32sI 36-byte binary shard layout), scripts/publication_preflight.py:57-198, and scripts/viewer_release_identity.py:1-92.

## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 72 → 72, work 60 → 60.
- Problem: AC1 unmet in part: 189 cross-test `from test_x import` statements remain (e.g. test_capture_metadata.py:14, test_raw_rebuild.py:15).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:93
- Status: Closed as superseded by the simplification plan (WS11 ct-2wsw, WS12 ct-uov2): the one-off measure scripts go with WS11; cross-test imports and digest helpers are not carried.
- See docs/reviews/2026-10-24-ticket-audit/README.md
