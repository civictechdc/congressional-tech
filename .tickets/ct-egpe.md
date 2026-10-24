---
id: ct-egpe
status: closed
deps: [ct-oxg6, ct-m9td]
links: [ct-q968, ct-bt1q, ct-3faj, ct-m9td, ct-qdkd, ct-nc7l, ct-a70m]
created: 2026-10-20T22:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Share the configured DocSpec client across archive and news

The news adapter duplicates runtime startup, temporary-file transport and schema conversion, defaults to a mutable debug binary, and removes producer files after uncertain requests. Reuse the maintained archive client and inject one pinned runtime; keep news merging and publication policy in news_lake.

## Acceptance Criteria

- Migrate both packages to one owner for host readiness, deadlines, EOF draining, exact-pin streaming and unknown-outcome Build/Update input custody (`NativeDatasets.run_table` and `NativeDatasets.update_table` in `packages/congress_api/src/congress_api/retention/docspec.py`). Keep feature request builders thin.
- Track both `source.parquet` (`replacements`) and `deletions.parquet` in `retained_producer_inputs()` (`docspec.py:398-414`, `native_capacity.py:218-235`, `docspec_backend.py:862-882`) whenever an `UpdateSpec` with deletions has an indeterminate outcome.
- Preserve explicit application schemas recursively across nested `Struct`/`List` fields, `UInt64`, actual `Decimal128` values (including negative `Sum` outputs widened to `DECIMAL(38, 0)`), nested null/empty/duplicate values and error meaning; do not infer every `Decimal` as `UInt64` (`docspec_backend.py:166-220`).
- Remove news free-port probing, mutable developer binary defaults (`DEFAULT_BINARY = '.../target/debug/docspec'` at `docspec_backend.py:74`), duplicated readiness/stream/custody code (`docspec_backend.py:394-936`), and temporary Arrow read files after caller migration.
- Test both actual callers locally with the same frozen binary; measure process count, copied/read bytes and memory. Preserve ongoing primary news/UI edits.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/congress_api/src/congress_api/retention/docspec.py and primary packages/news_lake/src/news_lake/storage/docspec_backend.py. Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring audit at `main` (`8221566d` / `33ce7877`):
1. `packages/news_lake/src/news_lake/storage/docspec_backend.py:74,94-265,394-936` still maintains a duplicate 540-line client (`DocSpecClient`, `_ArrowHttpStream`, `_validate_readiness`, `serve`, `_submit_with_custody`, `retained_producer_inputs`, `native_storage_schema`) instead of sharing `congress_api.retention.docspec` (`NativeDatasets` / `docspec_host.py`), and still defaults to mutable `DEFAULT_BINARY = '/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec'` (`:74`).
2. `packages/congress_api/src/congress_api/retention/docspec.py:419-420` (`NativeDatasets.update`) lacks an `update_table` producer-custody helper, and `retained_producer_inputs()` in both `docspec.py:398-414` and `docspec_backend.py:862-882` only inspects `source.parquet` (ignoring `deletions.parquet` staged at `docspec_backend.py:921-923`).
3. `_merge_field_type` / `application_schema` (`docspec_backend.py:166-220`) does not recurse into nested `Struct`/`List` fields when `expected_schema` is supplied and still maps `Decimal128(20, 0)` to `UInt64` when `expected_schema` is `None`.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: D+ (Reopened). Cloned workflow anti-pattern in 33ce7877: docspec_backend.py:394-936 expanded a second 540-line client instead of sharing congress_api.retention.docspec (NativeDatasets / docspec_host.py) and kept DEFAULT_BINARY = '.../target/debug/docspec' (:74). Sequenced behind ct-m9td for UpdateSpec custody.

**2026-10-21T00:31:34Z**

Implementation correction after review: the shared transport now lives in the new neutral workspace package packages/docspec_client (name docspec-client), not in congress_api. news-lake depends on docspec-client; congress_api.retention.docspec and .docspec_host are thin compatibility shims. This removes the duplicate 540-line news client and the mutable target/debug default. Remaining acceptance: measure process count, copied/read bytes and memory against one frozen binary, and re-pin QUALIFIED_DOCSPEC_RUNTIME after the docspec-rs delta.

**2026-10-21T00:31:42Z**

Transport now lives in packages/docspec_client; both domains depend on it, and the shims preserve existing import paths. The mutable target/debug default is gone (DOCSPEC_BINARY or PATH required).

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fixes: (1) added docspec-client to packages/congress_api/pyproject.toml dependencies; (2) fixed DocSpecClient.__init__ missing-binary DocSpecFailure construction (docspec_backend.py:404-411); (3) restored self._dataset_schemas lookup + restore_application_schema in DocSpecClient.read_arrow (:484-491) and recursive struct/list validation in _merge_field_type (:117-138).

**2026-10-21T02:20:25Z**

Implemented and verified: packages/docspec_client is the single neutral transport owner shared by congress_api and news_lake; test_ct_egpe_shared_host_across_archive_and_news_callers (tests/test_native_features.py) proves both callers share one Host instance and child PID on the same workspace; QUALIFIED_DOCSPEC_RUNTIME pinned to 96e38262 / 9a9f9952.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03a).
- Grades: proposal 90 → 90, work 84 → 84.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
