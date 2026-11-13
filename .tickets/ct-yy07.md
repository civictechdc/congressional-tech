---
id: ct-yy07
status: open
deps: []
links: [ct-a73a, ct-hz8y, ct-55qo, ct-aitp]
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

**2026-11-13T18:48:44Z**

The native geometry refusal occurs in the shared reader before the current routing strategy can recover it. Fix or expose this boundary upstream; do not weaken all geometry validation or catch every parser error as OCR. The 208 count is the retained audited snapshot, not a new classification of all current errors. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:16:53Z**

Shared code completed at spicy-docs d0d929ef (based ce38a3db): NativeGeometryError separates zero_area from outside_page and preserves the original line/display geometry. NativeOrOcr accepts explicitly named geometry fallback reasons; default remains strict and unrelated failures propagate. 57 shared API/observation tests and Ruff passed. Retained c84834bdffb4 page1 reproduces zero_area; a scripted backend boundary probe retains that refusal (no actual recognition or source-quality claim). Direct reviewer /root/ocr_ticket_completion/pdf_recovery viewed raw-review/geometry-page1.png and read c84834bdffb4.geometry.json and c84834bdffb4.diagnostic.txt: the old retained OCR preserves key job/wage figures but has from→trom and Affairs→Atfairs plus logo/signature artifacts. Evidence: repairs/pdf-offline-20261113/geometry-retained-boundary.json and data-review.md under the recovery root. Only the narrow retained specimen is inspected; classification of the remaining208 cohort and real CT fallback quality remain open. No broad catch or global geometry weakening was added.
