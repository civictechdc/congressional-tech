---
id: ct-9few
status: closed
deps: []
links: []
created: 2026-10-21T15:21:25Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, changes, contract, bug]
---
# Read the native ChangeDescriptor fallback and evidence_refs_changed fields by their serialized names

Independent CS300 audit finding (re-validated): packages/congress_api/src/congress_api/retention/native_features.py:48 reads descriptor.get('fallback_reason') and :86 reads effects.get('evidence_changed'), but docspec-rs serializes ChangeDescriptor.fallback (Option<ComparisonFallback>, src/model.rs:837) and ComparisonEffects.evidence_refs_changed (bool, src/model.rs:814). Both Python reads therefore always evaluate to None/False, so inspect_catalog_changes silently reports no fallback reason and no evidence effects.

## Acceptance Criteria

- In inspect_catalog_changes (native_features.py), read descriptor.get('fallback') (falling back to 'fallback_reason' only if present) and effects.get('evidence_refs_changed'), exposing both in the returned report under stable names.
- Extend tests/test_native_features.py with a case whose change stream forces a full-comparison fallback (e.g. force_full or a non-forward endpoint pair) and asserts the fallback reason is non-None, plus a case where evidence/receipt changes set evidence_changed True (or document that this path requires receipt updates and assert the wiring reads the correct key).

## Notes

**2026-10-21T15:33:55Z**

Fixed and verified: inspect_catalog_changes now reads descriptor['fallback'] (ComparisonFallback snake_case value) and effects['evidence_refs_changed'] (native_features.py:48-52,86). Added regression tests: forced_full stream asserts descriptor['fallback'] == 'forced' with no 'fallback_reason' key, same-pin stream has fallback None and path 'unchanged', and a receipt update between pins sets report['evidence_changed'] is True. tests/test_native_features.py: 9 passed.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03a).
- Grades: proposal 86 → 86, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
