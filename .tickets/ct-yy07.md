---
id: ct-yy07
status: closed
deps: []
links: [ct-a73a, ct-hz8y, ct-55qo, ct-aitp, ct-m704]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, geometry]
---
# Bound PDF rendering before allocation and finish geometry qualification

## Implementation update — 17 November 2026

Closed the completed geometry and rendering-bound scope. The opt-in reader checks predicted dimensions before allocating a raster and verifies actual dimensions afterward. Both fixed and adaptive paths refuse an over-cap page even at minimum DPI. The focused PDF tests pass against the final shared dependency; original accepted geometry recoveries remain credited.

The remaining generic adaptive-DPI/rotation adapter consolidation and unreviewed rotated-source fidelity are explicitly transferred to ct-hz8y's shared-reader/quality scope. That raster adapter still lives in CT. No remaining geometry correctness failure was demonstrated in the reviewed scope. The f1 pages 7–8 content omissions remain held under ct-hz8y/ct-a73a; closure does not certify their text.

## Audit baseline — 17 November 2026

The original 204-body geometry recovery is accepted and carried forward; do not repeat that cohort. Retain the earlier zero-area/native inspection qualification, exact versions and source limitations. The later 17-body memory cohort now has 15 accepted v12 outputs, one rejected photo-slide candidate and one unresolved ordinary-page source. ct-a73a owns reconciliation of those outcomes.

The new opt-in renderer has a concrete resource defect: `_OptInPDFPage.render` in `packages/congress_api/src/congress_api/parsers/pdf_opt_in.py:290` calls `get_pixmap` before `check_pixels`. Adaptive DPI stops at 36 even if the page still exceeds the cap. A no-allocation probe with a 10,000 × 10,000 point page and a 20-million-pixel limit reached a 36-DPI allocation request for 25 million pixels. The existing shared reader checks predicted dimensions before rendering.

## Scope and ownership

Own the pre-allocation bound and remaining opt-in native geometry/rotation behavior. Put reusable rendering behavior in SpicyDocs and leave CT's exact source/page selection policy local. ct-hz8y owns Tesseract backend reuse and recognition routing; coordinate the dependency update instead of implementing two shared-reader migrations. CT's current backport wheel lacks the newer upstream backend/options, so a qualified pin/backport is part of adoption.

## Acceptance Criteria

1. Check predicted raster dimensions before allocation, then verify actual dimensions afterward. At the minimum DPI, a page still over the cap refuses before rendering. Cover adaptive and fixed-DPI paths without raising the global pixel limit.
2. Preserve source hashes, original refusal evidence, strict defaults and actual reader/checkpoint identities. Keep zero-area, out-of-bounds, invisible-text, crop/rotation, damaged-source and unrelated-error controls distinct.
3. Qualify changed geometry/orientation behavior through the actual CT consumer and maintained shared implementation. Directly read a bounded source -> raster/native intermediate -> final sample, including relevant controls; bulk PDF review uses gpt-6.1-terra at medium reasoning. A useful repair does not certify unread pages.
4. Prove prior accepted text and selection are unchanged unless an explicitly qualified affected key changes. Hand source-outcome accounting to ct-a73a and export/quality adoption to ct-m704. Retain the original 204-body evidence without rerunning it.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

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

**2026-11-14T12:31:10Z**

Five-step follow-through: use ct-n3ik impact/priority to choose the next bounded native-only geometry work and preserve exact source/intermediate/candidate identities. ct-0a35 will check accepted text through search. Do not repeat all source scans or promote every geometry refusal to an OCR task; OCR remains paused and missing-source refetch deferred. Current unknown geometry/source causes remain explicit.

**2026-11-15T04:46:39Z**

Updated the current authorization text to the user's explicit 14 November instruction allowing asynchronous targeted OCR/refetch; historical pause notes remain preserved. No new geometry source qualification is claimed by the 26 unrelated one-page repairs. The remaining 204-body/1,344-page cause inventory still needs actual numerical/source evidence and selective consumer qualification.

**2026-11-15T07:55:50Z**

Accepted-set-v7 independently passed after eight actual PDF pairs were appended: six compositions/22 replacement pages and two retained-native one-page replays. Result repairs/accepted-text-adoption-20261114/accepted-set-v7-independent-review/result.json SHA15865e8b2d59ccbc30f1a1f36d8a8e46aae9ea077f45c4a61451f856f6aeea2c; selection SHA22756dbf6e8db2702532c26362bbbc1ba302e9841176f05aa1ee2f742f03677c. All1199 prior overrides/26exclusions/321 dispositions preserved; final1207 overrides,311716 selected texts,8142224 slots,2727045 OCR markers,57 valid empties and274 selected errors. Actual16 native rows match all fields; old eight reading controls suppressed and planted wrong digest rejected. Useful partial FTS limits remain explicit; no full export or SereneDB claim. Native replay versions truthfully preserve original refusals; no default policy restamp. Twenty-two source pages were previously directly reviewed; inherited pages were not newly audited.

**2026-11-15T08:36:23Z**

Frozen geometry-native-eight-20261115 inspection acquired eight exact retained originals through maintained archive custody, with zero publisher requests. Strict-first inspection made 30 native attempts across 18 source pages, no OCR/render: 0.7 seconds / 0.081 GiB. All twelve named failures have actual finite ordered in-page zero-width spans; the explicit maintained plain_text option returns their native text. Six controls retain strict outcomes. Independent Terra source/intermediary/normalized review is in independent-review/{review.md,pins.json}. Important gaps: 0c538d24bc35 p3 is a visible graphic slide with empty native text; cfede181ba22 p2 contains only a website graphic footer; bedacc p1 normalization drops two names present natively and p2 misses graphic Introduction. Chart labels are useful but numeric associations remain uncertain. These are scoped source findings, not whole-body adoption or a general reader downgrade.

**2026-11-15T08:44:02Z**

Count clarification: the 1,332 uninspected failed-page records comprise 1,325 in the other 196 bodies and seven additional bedacc pages (4, 11, 12, 15, 18, 19, 21) in the first-eight set. The retained inventory confirms ten bedacc failures; only pages 1, 16 and 22 were inspected. Pinned earlier evidence stays unchanged and receives a separate erratum.

**2026-11-15T09:22:13Z**

The first eight-source review covers every physical page, including the seven additional bedacc failures. Exact native parity: repairs/geometry-runners-20261115/parity/result.json; 41 pages, 60 native attempts, 2,478,875 source bytes hashed, sixteen PDF opens and no OCR. Seven graphic candidates subsequently used nine actual recognition calls at 0.439 GiB peak RSS; the 344-second wrapper duration includes waiting for the shared one-body lock and is not recognition timing. Actual rasters/observations/finals are under graphics/. Independent semantic review and complete-body staging remain. The remaining census is exactly 196 bodies / 1,325 failed pages, with no default-policy change.

**2026-11-15T09:24:53Z**

Independent Terra review now qualifies all seven exact graphic candidates as useful FTS improvements. Missing slide labels and Medicare headings are restored in source order; map/chart/table limitations remain explicit. Exact evidence: repairs/geometry-runners-20261115/graphics/independent-review/{review.md,pins.json}. Eight-body complete pairs are being assembled from these candidates and the retained source-reviewed native pages; no new selection follows automatically.

**2026-11-15T10:52:30Z**

Evidence: repairs/geometry-wholebody-recovery-20261115/final-03/whole-candidate-review/{review.md,result.json,priority-pages.json}, independent-pilot-review and independent-continuation-review/batch-{01,02}. The 193 eligible candidates have 4,291 slots / 323 OCR markers, residual three have 154 slots / 89 markers. The first eight separately adopted bodies are outside these 196. Existing screens nominate 342 pages with overlapping encoding/fragmentation/empty/sparse/residual reasons; this is not 342 source failures. Terra medium directly read eight additional risk-stratified pages: two symbol/bullet warnings, two partial word-fragmentation cases, one image-only aerial page, two visually blank pages and one correct sparse divider. 487 page 82 recovers useful questionnaire fields; page 1 recovers title/date but mostly garbles its illustrative screenshot collage and stays held. No geometry candidate among these 196 is adopted yet.

**2026-11-15T12:11:18Z**

Accepted-set-v10 selection SHA eb8473ab6163d3ab4b16f4fa56754a5b72b9391065aeedf3138db02eaaf3b111; native snapshots body_text 4383126096555098411 and readings 6734786965736914418. Independent result SHA 016d5932ef5a62d09a706974da210c7adb37e026efc19b8a833529f8568cd9d0 verifies all 388 new native pairs, append ancestry, all 1,217 prior choices, 339 prior disposition lines, preserved dbaa and rejection of a planted wrong digest. The new delta contains 234,583,311 UTF-8 bytes / 114,416 slots / 80,443 OCR markers. Source review covers 94 of those slots; 114,322 remain source-unread with exact limits retained. The final 196 geometry selections contain 4,445 slots and 414 OCR markers, including Groq page1 and regional/Vision page82 in487. Terra source scope is 56 pages across this cohort; the preceding eight-body batch had all 41 source pages directly reviewed. The other sources/pages remain explicitly unread. Native census evidence is geometry-runners-20261115/census/batch-01 through batch-28: 1,300 plain-text returns and 25 residual refusals, with original numerical evidence preserved. Frozen geometry-wholebody-recovery-20261115/final-03 and geometry487-composition-20261115 bind actual complete outputs. All 18 nominated empty roles were source-dispositioned; useful partial graphs, names, signatures and word fragmentation remain documented. The optional typed-error compatibility fix is being integrated without changing the current installed reader's declared versions or fixed fixture outputs; strict global geometry defaults remain.

**2026-11-15T13:34:46Z**

CT PR180 merged at 293469c55cc9571c5471878891d902b7e89286d5 after six offline shards, validation and MCP checks passed. Accepted-set-v11 preserves the prior geometry choices; no new geometry data was adopted. The separate memory17 preflight has exact original custody and source-reviewed samples: two oversized pages contain approximately 72-DPI scans, so rendering at 200 DPI causes unnecessary enlargement. Whole-page 65/71-DPI samples are readable, including the native 079 overlay; the form is sideways. The prepared pilot preserves overlays, uses an explicit whole-raster rotation and inverse coordinate map where needed, retains the 20-million-pixel guard and strict native defaults, and gives partial probes no completed-body status. Evidence: repairs/memory17-source-preflight-20261115/source-review-samples/.

**2026-11-17T09:17:02Z**

Manual audit credits the accepted original 204 bodies and later 15 memory-cohort recoveries. Rewritten around the confirmed allocation-before-pixel-check bug and remaining shared rendering/geometry qualification. A no-allocation probe reached 25 million predicted pixels at 36 DPI despite a 20-million limit. ct-hz8y owns shared Tesseract reuse; ct-a73a owns unresolved/rejected source accounting. Do not repeat accepted geometry recovery. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:52Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved. Geometry/render-bound scope closed; generic adaptive/rotation consolidation and remaining source-fidelity review explicitly transferred to ct-hz8y.
