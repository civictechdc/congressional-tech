---
id: ct-x0nk
status: closed
deps: []
links: []
created: 2026-10-21T15:21:26Z
type: chore
priority: 3
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, hygiene, tests]
---
# Clean up docspec transport hygiene: dead ternary, duplicated schema mapper, test-only stream class, and missing setup-script unit test

Independent CS300 audit finding (re-validated), four items: (1) packages/docspec_client/src/docspec_client/docspec.py:646 contains a dead ternary 'Boolean(force_full) if False else bool(force_full)' where Boolean is not even imported; (2) packages/news_lake/src/news_lake/storage/docspec_backend.py:90-119 duplicates native_storage_schema already exported by docspec_client.docspec; (3) docspec_backend.py:368 defines _ArrowHttpStream which is imported only by packages/news_lake/tests/test_docspec_backend.py:28,683-688; (4) .github/scripts/setup-native-runtime.py (artifact_descriptor/install/engine_credentials) has no direct unit test in tests/.

## Acceptance Criteria

- Replace the dead ternary in docspec.py:646 with bool(force_full).
- Make docspec_backend.py delegate native_storage_schema to docspec_client.docspec.native_storage_schema (keeping __all__ exports stable) so the storage mapping has one owner.
- Move _ArrowHttpStream into the test module that uses it (or replace its assertions with docspec_host.ArrowResponse framing checks).
- Add a unit test for setup-native-runtime.artifact_descriptor/install covering descriptor validation rules and refusal paths without network access.

## Notes

**2026-10-21T15:33:55Z**

Fixed and verified: (1) dead ternary replaced with bool(force_full) (docspec_client docspec.py compare payload); (2) docspec_backend.native_storage_schema now re-exports the docspec_client owner instead of duplicating the mapping; (3) _ArrowHttpStream and _ARROW_STREAM_EOS moved into packages/news_lake/tests/test_docspec_backend.py next to their only user, and the backend's now-unused io/time imports were removed; (4) added setup-native-runtime artifact_descriptor (8 refusal cases incl. wrong platform, short revision, bad bucket, mismatched key, missing remote feature) and engine_credentials (4 refusal cases) unit tests loaded via importlib without network. Full sweep: tests/test_native_features.py + packages/news_lake/tests/test_docspec_backend.py + tests/test_docspec_runtime.py = 58 passed.
