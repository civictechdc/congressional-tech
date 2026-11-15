---
id: ct-t4p3
status: in_progress
deps: [ct-aitp]
links: [ct-a73a, ct-n3ik, ct-aitp, ct-l3xd]
created: 2026-11-13T17:46:16Z
type: bug
priority: 2
assignee: mikewolfd
tags: [body_text, pdf, ocr, recovery]
---
# Qualify page-level OCR crash recovery and alternate recognition settings

The formerly crashing 244-page 9a0d94fb19ef PDF now completes through the maintained CT path with 244 valid page checkpoints. Page 125 uses an independently reviewed seven-region Vision result with useful partial FTS text and named roster/contact limitations. Independent whole-body sampling found material garbling on page 124; two Vision candidates remain held. A one-page Groq/Qwen candidate now passes independent source-to-output review for readable biography text. Its separate model metadata is unreliable and must not become document metadata. Exact page 124 composition, preserved other 243 pages, native adoption and accepted selection remain.

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

**2026-11-13T21:16:53Z**

Exact-page override/checkpoint support now allows candidate backend settings on page125 without discarding unchanged matching pages. No alternate real backend ran. Direct reviewer /root/ocr_ticket_completion/pdf_recovery read the original crash-page125.png, native/intermediate trace, and completed one-page-whole.log/one-page-four-bands.log under recovery/raw-review. One-band omits the officer roster and changes the printed footer telephone202-872-8688 to202-372-8688; four-band still mangles names/labels and misses officers. Both retained candidate outputs are rejected for source quality despite successful exits. The three-band trace still records a first-strip segmentation fault. Real accurate page125 replacement and complete244-page consumer/resume acceptance remain blocked by the OCR pause, not declared passed by the scripted crash fixture.

**2026-11-15T08:36:23Z**

Actual complete 244-page candidate: repairs/crash244-dispatch-20261115/attempts/ccd3bc5093344d4ba363d4d5f669cced/. Independent source sample covers pages 1, 124, 125, 126 and 244 and names all other unread pages. Page 125 actual seven-region Vision output is useful partial FTS, with contact/roster errors preserved. Page 124 Vision retry remains rejected for widespread garbling. Separate one-request Qwen result passes direct source/raw-provider/final reading: repairs/crash244-p124-groq-20261115/independent-review/, text SHA 121fcc9986a05ec5cffc683e6508dbccef71aae1436acdea0d6a36c754380890. Its bill classification, graduation-year document date and printed-page identifier are wrong and excluded. Candidate composition and selection remain. Provider-provenance adapter PR #176 merged at 9e507b62c0f9d52790fd535775217f94f91bcb57 after both latest CI workflows passed.
