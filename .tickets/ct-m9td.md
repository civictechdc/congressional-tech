---
id: ct-m9td
status: closed
deps: [ct-3faj, ct-qdkd, ct-a70m]
links: [ct-egpe, ct-qdkd, ct-nc7l, ct-3faj, ct-a70m]
created: 2026-10-20T23:52:13Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, recovery, custody, retention]
---
# Track UpdateSpec replacement and deletion files in producer custody and operator retention

ct-3faj, ct-qdkd, and ct-a70m implemented unknown-outcome producer file custody and retention protection for single-file RunSpec (source.parquet), but left multi-file UpdateSpec (replacements + deletions) incomplete: (1) NativeDatasets (packages/congress_api/src/congress_api/retention/docspec.py:398-420) has no update_table custody helper and retained_producer_inputs() only checks request.parent / 'source.parquet'; (2) _inspect_producer_inputs and plan_protected_retention (packages/congress_api/src/congress_api/retention/native_capacity.py:218-235,398-404) only read payload.get('expected_digest') and item.get('input'), ignoring UpdateSpec replacements ({'path', 'digest'}) and deletions ({'path', 'digest'}); and (3) DocSpecClient.update_table (packages/news_lake/src/news_lake/storage/docspec_backend.py:862-882,912-935) stages deletions.parquet (:922) but never reports or tracks deletions.parquet in retained_producer_inputs().

## Acceptance Criteria

- Add NativeDatasets.update_table in packages/congress_api/src/congress_api/retention/docspec.py with the same pre-persisted request.json and unknown-outcome retention guard as run_table.
- Update retained_producer_inputs() (docspec.py:398-414), _inspect_producer_inputs() (native_capacity.py:218-235), and plan_protected_retention() (native_capacity.py:398-404) to inventory and protect all producer Parquet files referenced by request.json (input, replacements.path, and deletions.path) and sum their exact byte sizes in outstanding_producer_bytes.
- Add unit tests in tests/test_native_capacity.py and tests/test_docspec_runtime.py covering indeterminate UpdateSpec requests with both replacements.parquet and deletions.parquet.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to address the CS 300 deduction on ct-3faj / ct-qdkd / ct-a70m / ct-egpe: multi-file UpdateSpec custody (replacements.parquet + deletions.parquet) in docspec.py:398-420 and native_capacity.py:218-235,398-404.

**2026-10-21T00:31:34Z**

Implemented: shared NativeDatasets.update_table persists request.json before submission and retains replacements.parquet + deletions.parquet on indeterminate outcomes; producer_input_entry sums every referenced producer file; retained_producer_inputs, native_capacity._inspect_producer_inputs, and the news adapter report all files. Tests: tests/test_docspec_runtime.py update_table custody (2), tests/test_docspec_input_custody.py (25), tests/test_native_capacity.py (17) pass.

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fix -> Grade: A. (1) plan_protected_retention (native_capacity.py:405-413) now iterates item.get('files', ()) so both replacements.parquet and deletions.parquet are added to protected_object_paths; (2) NativeDatasets.update_table (packages/docspec_client/src/docspec_client/docspec.py:462-537) stages replacements.parquet and deletions.parquet inside a single mkdtemp request-* directory, removing DocSpecClient._request_directory and its unsafe shutil.rmtree on retry (docspec_backend.py:508-520); (3) removed unused positional table parameter requirement. Verified: test_native_capacity.py (17 passed), test_docspec_runtime.py (31 passed), test_docspec_input_custody.py (25 passed).
