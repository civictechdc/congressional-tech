---
id: ct-fqgf
status: closed
deps: []
links: [ct-esm4, ct-n3qy, ct-vxzu, ct-ma8a, ct-vd5b, ct-r46l]
created: 2026-10-19T17:00:40Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Compare seals with the caller's loaded bytes

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Do not make sealed_inputs the only reader. Extract a digest and source-preparation comparison that uses the caller's already-loaded bytes and the caller's error. Leave sealed_inputs as the inventory reader for reconcile and coalesce. Leave verify_import's 64 MiB read and invalid() errors. Leave verify_batch's readiness overlay.

This comparison is a prerequisite of the corpus-recovery package.

## Acceptance Criteria

- The extracted digest and source-preparation comparison uses the caller's already-loaded bytes and raises the caller's error.
- sealed_inputs remains the inventory reader for reconcile and coalesce.
- verify_import still performs its 64 MiB read and still reports invalid() errors.
- verify_batch still applies its readiness overlay.
- Fixtures without bodies.json still pass.
- tests/test_dispatch_corpus_recovery_publication.py::test_bounded_import_evidence_names_malformed_fields_and_keeps_primary_error still passes: JSON_BYTES is 4 and the manifest read raises the byte-budget error.


## Notes

**2026-10-19T18:10:39Z**

9e980ee5c0edbc544cfdc34ba2c14df4f0b3d39c Compare sealed batch bytes with each caller's own error.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch standalone).
- Grades: proposal 87 → 91, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
