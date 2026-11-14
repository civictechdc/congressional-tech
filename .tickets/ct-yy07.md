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

**2026-11-13T22:31:39Z**

Confirmed and repaired a diagnostic-only loss in the successful native-geometry fallback path. The shared reader retained the original page1 zero-width TX line, display bounds and page geometry for retained c84834bdffb4f04d0c6c731fa48fb33ef3e5fed3d5bc630fa74d1290bb2c5b75; CT had emitted only the refusal message and an empty native line array after scripted fallback. _PageRun.observe now preserves the named page/line/display_bbox/geometry details only for native-geometry-refused observations, excluding unrelated opaque raw objects. The actual retained-source scripted probe preserves the complete reading with evidence off/on; no recognizer, provider or publisher request ran. Fixed reader sample digests and declared versions are unchanged, and refreshed source fingerprints record the diagnostic-equivalence decision in docs/development.md. Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/geometry-reconciliation-20261113/{diagnostic-retention-before.json,diagnostic-retention-after.json,probe-diagnostic-retention-after.py}. The scripted text is a transport control, never a qualified replacement. Exact remaining body/page reconciliation and source-quality acceptance stay open.

**2026-11-13T22:38:13Z**

Frozen geometry reconciliation enumerates all 208 body identities and 1,350 failed-page identities from hash-verified committed receipts and complete retained diagnostics. The previous 208 count is bodies, not pages. Four outcome messages were 32 KiB tails; full diagnostic files restore the omitted early page identities. Only c84834bdffb4 page 1 has supported numerical/source classification (zero-width TX inside displayed bounds). The other 207 bodies / 1,349 pages remain explicitly evidence_missing; no outside-page or malformed/native cause is inferred from the old exception label. Ten retained source/audit manifests identify only the known c848 local original, which is not a claim that other captured archive objects are absent. Exact keys, ETags and recorded sizes remain in the inventory for bounded native-only archive inspection.

Current shared geometry/API isolation remains strict by default and reason-specific when explicitly opted in; CT's declared page_rule enables neither reason. The audit also reproduced a diagnostic transport loss after successful fallback: shared native observation.raw retained the refused line/display geometry, but CT page_extracted dropped it. Root fixed this in 9e868a5b0cb6a6c8a2f7cd3dda9596d64fc45de6, retaining only page/line/display_bbox/geometry for native-geometry-refused observations. Independent direct review of the raw c848 page, native failure, shared observation and actual CT before/after output confirms geometry retention and an unchanged scripted reading, with the code hash bound to the commit. No actual recognition or quality acceptance follows.

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/geometry-reconciliation-20261113/{data-review.md,body-inventory.jsonl,page-inventory.jsonl,unreviewed-bodies.txt,summary.json,independent-diagnostic-fix-review.md}. Keep this ticket open for actual cause/source qualification of remaining pages, real CT fallback quality after OCR is resumed, and declared-version/selection acceptance. OCR remains paused; publisher refetch is deferred; no crop or checkpoint adoption occurred.

**2026-11-13T22:48:50Z**

Three exact captured-archive originals were retrieved with full-range/If-Match/ETag-MD5/gzip-size/body-SHA verification (214,307 stored bytes; 246,046 decoded bytes), without publisher fetch or recognition. Direct named review of d128b929c3b1… p5, 924eb1c45958… p1–3, and 15611eacbdfb… p1 confirms finite ordered in-page zero-width first-refusal lines. Geometry cause evidence now covers 4/208 bodies and 6/1350 pages; 204 bodies/1344 pages remain numerically unresolved, explicitly inventoried. This is reason coverage, not accepted text quality.

Two bodies also end inside declared streams and have garbled/clipped rendering, missing font data, and native text omissions: d128 object 48 declares 5481 stream bytes with 1,262 retained; 924 object 104 declares 62,475 with 49,160 retained. Both lack startxref/trailer/EOF and require native repair on open. Full archived body identity is verified; publisher-transfer completeness/truncation origin is not. 156 renders coherently but its failing 'Dr. ' span is alpha 0, and native text has split words/omitted graphic-header text. Current CT NativeText rows correctly remain error/failed_pages with typed raw diagnostics preserved. A future explicit unlocated-text policy must not silently qualify these cases or treat in-page invisible text as visible. Native-only candidate comparison on c848/156 is next; d128/924 are damaged-source failure controls. OCR remains paused, publisher refetch deferred.

Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/geometry-reconciliation-20261113/archive-native-sample/data-review.md; classification-delta.jsonl; artifact-hashes.json. This note supplements the frozen geometry reconciliation; it does not close ct-yy07/ct-a73a or change production selection. The damaged-source findings also inform ct-a73a/ct-en4n without asserting a new publisher fetch is authorized.

**2026-11-13T23:17:11Z**

Shared native-only inspection follow-up is now in SpicyDocs PR28, https://github.com/mikewolfd/spicy-docs/pull/28, stacked on shared feed/XML PR27. Explicit DefaultReader(native_zero_area="plain_text") requests the existing PyMuPDF plain-text representation only when strict native extraction refuses finite, ordered, in-page zero-area line bounds. Default strict behavior remains unchanged; outside-page, inverted and nonfinite geometry still refuse. Original line/coordinate/refusal evidence stays attached, with policy identity recorded on every opt-in page. CT pins, checkpoints and routing have not adopted this option.

Direct review by /root/ocr_ticket_completion/pdf_recovery and the coordinating agent covers four source bodies/six failed pages. c848 and 156 regain substantive address/body and biography text; word splits, graphic headers and signatures still limit completeness. The d128 and 924 originals have structural/font damage, so their candidate text remains unsuitable for selection. Source cause is still unresolved for 204 of 208 bodies (1,344 of 1,350 failed page records). The reviewed packet and independent composition binding are in repairs/geometry-reconciliation-20261113/native-plain-{candidate,composed}/. All 44 combined output artifacts matched the directly reviewed standalone packet at 61aeeb84.

This is a native candidate inspection improvement, not an accepted transcription or a production adoption. Source-quality, CT consumer/version identity and held-out coverage gates remain open. OCR remains paused and publisher refetch deferred.

**2026-11-14T05:39:37Z**

Shared native inspection is merged in spicy-docs PR28 (merge a1bed8ce820aecd95c95c0af3f9d13f0254b105c); all CI passed at 26bcf69aa3778fa492628f3fa2b62aa35d55946d. DefaultReader(native_zero_area="plain_text") is an explicit inspection option. Strict defaults remain; nonfinite, inverted and off-page geometry still refuses. The composed source reproduces the already directly reviewed artifacts exactly.

Root independently viewed c848's PESA letter page 1 and 15611e's Linsey Haram biography page 1, then read native evidence, strict refusals and actual normalized candidates. The visible prose is substantially recovered but word splits remain, and logo/header/signature graphics are omitted. These are development examples and unaccepted candidate text. Evidence: repairs/geometry-reconciliation-20261113/root-direct-native-review-20261114.md and its artifact manifest. Cause coverage remains four bodies / six failed pages; 204 bodies / 1,344 failed pages remain unresolved. CT retains its existing qualified wheel; adopting this option, qualifying output and selecting it remain separate work. OCR stays paused.
