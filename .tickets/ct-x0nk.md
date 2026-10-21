---
id: ct-x0nk
status: open
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
