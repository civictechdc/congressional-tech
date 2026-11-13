---
id: ct-yy07
status: open
deps: []
links: [ct-a73a, ct-hz8y]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, geometry]
---
# Recover PDF native-geometry failures through a qualified OCR fallback

The recovery checkpoint has 208 errors reporting native text falls outside displayed page bounds. On retained specimen c84834bdffb4, source inspection localized a zero-width TX span; an OCR probe recovered 2,496 bytes. This establishes one narrow recoverable geometry case, not that all 208 errors share it. The strict native check currently prevents the otherwise readable page from reaching OCR.

## Design

Keep the shared native geometry validation meaningful. Distinguish degenerate zero-area spans from genuinely external text, rotated/cropped pages and unrelated extraction failures. Preserve the original native refusal and exact source/page evidence while allowing a narrowly qualified page-level OCR fallback. Reuse the existing render/recognizer path and recorded settings.

## Acceptance Criteria

1. Inventory and classify the 208 retained failures by actual page/span geometry; identify records not inspected.
2. Reproduce the c84834bdffb4 failure and source-confirm its recovered passage through the real CT consumer.
3. Cover zero-area, out-of-bounds, crop/rotation and unrelated-error controls; unrelated failures retain their reasons.
4. Preserve source hashes, refusal history, page offsets and OCR provenance under a declared version. Independently verify source text and a planted omission before affected-body rereads/publication.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.
