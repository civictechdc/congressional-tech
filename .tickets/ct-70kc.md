---
id: ct-70kc
status: closed
deps: []
links: [ct-esm4, ct-ma8a, ct-r46l, ct-4r1c]
created: 2026-10-24T18:15:54Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-98sm
---
# WS4: provenance pinning from the git commit

The recovery import pins code from a hand list (`dispatch_corpus_recovery_import.py:107-122`) that misses `docspec_client` and `congress_shared` custody and storage, the code that writes raw datasets. The catalog fingerprints hash the `document_index.py` and `raw_catalog.py` shims, not `index/*` (audit hotspot 6).

First move: replace the self-referential test (`test_dispatch_corpus_recovery_import.py:111-117`) with a completeness test: every repo-owned module loaded during an import dry run is covered by the pin.

Owner decision (plan open question 4, answered): recovery imports refuse uncommitted code and record the git commit plus the `uv.lock` digest. So one `code_identity()` helper returns the HEAD commit (tree hash) plus the `uv.lock` digest and refuses when `packages/` or `scripts/` has uncommitted changes. The import pin and both catalog fingerprints use it, and the hand list goes.

## Acceptance Criteria

- The completeness test lands first.
- A dry-run import shows the identity covers `docspec_client`, and an import from a dirty tree is refused.
- Recovery admission validates the event shape once where events are parsed (`admission.py:75-95`), and the 7-case test asserts which check fired.
- This lands before WS10 deletes `document_index.py` and `raw_catalog.py`.
- R-check 1-3 pass.


## Notes

**2026-10-30T16:49:25Z**

Verified completed in docs/plans/simplification-plan-20261024.md §6.2.6 (B6, cef-l1ws, cefr-4pxk) and F5 G12 (commit 8978b3bb): packages/congress_api/src/congress_api/retention/provenance.py and packages/congress_api/src/congress_api/lake/versions.py (version_digest) pin clean git commit, file, and uv.lock digests across receipt writers, recovery imports (reconcile.py), and lake producers, and legacy admission.py/guards.py were deleted in commit 8978b3bb.
