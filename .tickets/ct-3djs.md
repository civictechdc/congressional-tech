---
id: ct-3djs
status: closed
deps: []
links: [ct-lu4i, ct-fw0m]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Reuse catalog reference validation within one build

A normal rebuilt catalog checks the same source/document references in catalog_staging.py:565, raw_catalog.py:351, and catalog_publication.py:135. Each call rebuilds a temporary SQLite reference index.

Reuse the existing process-local CatalogPairValidation pattern, bound to unchanged files and validator identity.

## Acceptance Criteria

Count one complete reference validation for the same owned pair across these handoffs. Rewritten files, changed validator, bad references, and a fresh process must require validation or refuse reuse. Existing interruption and concurrent-selector tests still pass.

<!-- grade-followup:start -->
## Grade review follow-up

Include publish_catalog, _publish_result, validate_catalog_pair, validate_document_indexes and _validator_identity; distinguish in-process validator binding from the outer dependency pins.

- Keep full initial reference/body validation, invalidate on changed input/runtime/validator, and propagate one bound proof through local recovery and normal publication.

Include publish-filename-viewer.verify as a consumer of shared manifest/path rules and existing bound pair proof; keep expensive reference validation separate from a formatting refactor.

- Direct and proof-backed paths enforce consistent selected-pair rules; stale/forged proofs cannot skip checks.
- No extra complete reference pass is introduced merely to centralize validation; absent proof still requires full file integrity verification.

[Function scope and checks: 8 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:221). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:18:42Z**

Implemented issued reference/content/pair proofs through staging, raw publication and recovery Store admission. Normal raw rebuild test counts exactly one complete reference scan; selected-copy handoff retains full hash/metadata/coverage checks without another reference pass. Direct viewer verification shares canonical selected-manifest rules without adding reference scans. Forged copied proofs, rewrites and changed validator fail. 134 tests + 5 subtests pass; tracked custody receipt documents local/runtime versus outer pins.

**2026-10-18T21:07:54Z**

Final regression assertions now recognize earlier custody refusal after a verified catalog file is rewritten and shared generation-path validation. Existing no-publication-write assertions remain intact; related offline checks pass.

## Audit 2026-10-24

- Verdict: SUPERSEDED (batch d8z3a).
- Grades: proposal 74 → 68, work 72 → 72.
- Problem: The single-build validation proof was later dropped (ct-u7gg), and `validate_catalog_pair`/`CatalogPairValidation` have no production caller.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3a/d8z3a-verdicts.md:73
- Covered by: WS10 (ct-r6xw), which removes the `CatalogPairValidation` class and keeps `validate_catalog_pair`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
