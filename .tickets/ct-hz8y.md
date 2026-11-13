---
id: ct-hz8y
status: open
deps: []
links: [ct-kfsd, ct-n3ik, ct-a73a, ct-yy07, ct-55qo, ct-aitp]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, routing]
---
# Route incomplete native PDF layers and vector-only writing to OCR

A native-text count of at least 50 can suppress OCR even when it consists only of a caption or margin notice; image-free vector lettering can be skipped entirely. Source review confirms Q005 vector tables, Q007 captions over image tables/charts, Q009 headers over scanned appendices, and Q010 a vertical publisher notice beside omitted journal content. S167 has more than 50 margin characters and vector body text with no raster images; S188 has already-corrupt native English alongside a legitimate Cherokee sidebar. Document averages and zero-OCR filters miss mixed-document failures.

## Design

Spicy-docs owns reusable page evidence and routing hooks; CT owns the versioned congressional policy. Reuse the retained text/offset census for candidate ranking and maintained native/region/OCR capabilities. The census has no image/font/vector features and is not a completeness or typeset classifier. Consider X and Y coverage, orientation, repeated furniture, vector/raster content and source role. The central 80%-height proxy already misclassifies Q010. Keep incomplete accurate native fragments distinct from corrupt native text and new OCR errors; qualify composition order and overlap before combining native answers with OCR questions.

## Acceptance Criteria

1. Recover the named tables, values, labels, prose and footnotes on Q005 pages 70-72, Q007 pages 6/12/16, Q009 pages 37/47 and Q010 pages 2/9/16, plus S167 and S188.
2. Independently inspect held-out source pages and plant a substantive omission and a plausible wrong value; both must fail.
3. Preserve legitimate repeated amendments/covers, roll-call forms, blank/logo-only pages, short covers, redacted grids, rotated tables, sidebars and non-Latin text. Vector ink or low density alone cannot establish an omission.
4. Report routing reasons, reading versions, accuracy/omissions, peak memory and reread cost separately. Reuse prior census work and reread only the qualified affected set.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T18:48:44Z**

The audit visually rechecked S167 page 1 and Q007 page 6. Count >=50 is not a coverage test. Reuse upstream region/override APIs, but qualify reading order (unanchored regions append). ct-aitp owns page persistence; ct-55qo owns final selection. The 18,777-body triage inventory is a candidate inventory, not 18,777 confirmed failures. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:16:53Z**

Exact-source/page candidate routing is now implemented with PageRule.page_overrides around maintained spicy-docs strategies. No generic density/image threshold was substituted for source qualification and no production override was adopted. Direct content review by /root/ocr_ticket_completion/pdf_recovery: Q007 page6 original contains the European debt table (Belgium96.20, Germany83.20, Greece144.90) and G10 stacked chart/legend; retained native and final text contain only Figure3/Figure4 captions. Chain: .cache/archive-release/investigations/text-quantity-review-20261113/quality-expansion/{sources/Q007.pdf,renders/Q007-p0006.png,renders/Q007-p0006.native.txt,renders/Q007-p0006.retained.txt}. No new recovered output exists while OCR is paused; named-page recovery/held-out accuracy remain open. Parent review also found C015 preserves printed fields but omits the visible handwritten signature and moves its printed date; it is a cleanup/selection-equivalence control, not a fully transcribed form.
