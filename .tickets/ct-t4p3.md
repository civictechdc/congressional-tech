---
id: ct-t4p3
status: open
deps: [ct-aitp]
links: [ct-a73a, ct-n3ik]
created: 2026-11-13T17:46:16Z
type: bug
priority: 2
assignee: mikewolfd
tags: [body_text, pdf, ocr, recovery]
---
# Qualify page-level OCR crash recovery and alternate recognition settings

The retained 244-page PDF 9a0d94fb19ef crashes Apple Vision performRequests_error_ on the first strip of page 125. CPU-only recognition also crashes. One-band and four-band probes complete with different output quality, so avoiding the crash is insufficient acceptance. Shared page persistence and resume now belong to ct-aitp; this ticket owns accurate alternate recognition for the crash case.

## Design

Reuse ct-aitp for checkpoint identity and retries. CT owns scoped fallback policy; spicy-docs owns supported render/recognizer settings and their reported identity. Reuse valid page work only when source, page, renderer and recognition policy match. Preserve all failed attempts. Qualify alternate strip settings or a maintained independent backend on the exact failing page; do not put every fast-path page in a new process. Coordinate recognition quality and typeset/scanned policy with ct-n3ik.

## Acceptance Criteria

1. Reproduce and isolate page 125 and finish the document through the actual CT path without discarding valid matched checkpoints.
2. Independently compare names, labels, numeric values, omissions and reading order for candidate settings; planted plausible wrong values fail. A successful process exit alone does not pass.
3. Integrate the qualified fallback with ct-aitp; its interruption and identity checks must pass, and ct-55qo must select only the accepted reading.
4. Measure wall time, peak memory and fallback frequency; retain no-text photo controls and an explicit outcome if no accurate fallback qualifies.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T18:48:44Z**

Checkpoint implementation and its generic acceptance have been consolidated into ct-aitp; this ticket remains open for real page-125 fallback quality and scoped worker isolation. No real OCR probes while paused. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.
