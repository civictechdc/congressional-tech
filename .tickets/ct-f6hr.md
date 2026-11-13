---
id: ct-f6hr
status: open
deps: []
links: [ct-cbkz]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, html, xml, spicy-docs, compatibility]
---
# Handle retained HTML encoding and XML compatibility failures under explicit policies

The retained recovery checkpoint contains 231 HTML UTF-8-only refusals, 284 XML DOCTYPE-policy refusals and one markup max_events refusal. Reviewed specimens establish Windows-1252 HTML and an empty internal XML subset as recoverable compatibility cases. Confirm remaining members before generalizing. One malformed-XML refusal stays separate. Existing ct-cbkz / upstream ss-mkxe cover text normalization, not these encoding, XML policy or resource acceptance gaps.

## Design

Spicy-docs owns explicit decoding, safe XML parsing and bounded/streaming markup consumption; CT owns declared reading policies, measured worker admission and selective CPU-only rereads. Reuse maintained readers and verify current shared-reader work before implementing overlapping fixes. Record the selected encoding and original byte identity; do not silently insert replacement characters. Permit qualified empty subsets without entity expansion or external resource loading. Measure the actual event-limit specimen before increasing limits. Keep unrelated PDF output unchanged by this markup change.

## Acceptance Criteria

1. Read the retained legacy-encoding, empty-subset and max_events specimens through the actual CT consumer, preserving source-confirmed text. Report exact affected predicates and unreviewed members.
2. Cover conflicting/missing encoding declarations, UTF-8, preformatted HTML, empty subsets, entity declarations, malformed/truncated XML and large valid input. Prove no external XML fetch or entity expansion; preserve original byte locations where the API exposes them.
3. Measure peak memory and time on the largest retained examples under worker supervision. Named malformed/unsupported inputs remain explicit refusals.
4. Integrate with ct-cbkz without conflating normalization and compatibility. Declare versions, reread affected CPU markup cohorts and reconcile current selection, active refusals and historical evidence.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.
