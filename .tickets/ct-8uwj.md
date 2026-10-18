---
id: ct-8uwj
status: closed
deps: [ct-sv16, ct-3djs, ct-1dsp, ct-zkzt, ct-gubr, ct-hnxb, ct-idhg, ct-zb9y, ct-lvvr, ct-bs70, ct-9at7, ct-fw0m, ct-rrfm, ct-m59w, ct-p6aq, ct-zika, ct-qyey, ct-15wc]
links: [ct-x7vx]
created: 2026-10-18T19:28:39Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018]
---
# Verify combined publication efficiency gains

Individual speedups can overlap, shift work between stages or increase memory. The combined changes need one reproducible cost comparison across full publication, unchanged polls and explicit restart.

Use the completed stage-cost and optimization tickets; do not add their percentages or infer full performance from codec fixtures.

## Acceptance Criteria

At a pinned integration revision, compare the combined implementation on identical authorized inputs/runtime with exact output and review-binding checks. Report total time, critical path, peak process-tree memory, scratch, total bytes and requests. Keep success/no-op/restart results separate and retain failures. No production retry, limit change or source acquisition is authorized by this ticket.


## Notes

**2026-10-18T19:47:55Z**

Combined verification now also covers the named verified-file ownership, alias-index budget, transfer-receipt reuse, browser normalization/decode, provenance and detail-rendering changes. These are integration prerequisites only; the implementations can proceed independently. Do not sum overlapping percentage gains.

**2026-10-18T21:04:16Z**

All implementation prerequisites are merged. Final verification uses three fresh alternating baseline/candidate trials with identical retained fixture, runtime and instrumentation; exact values, reader metadata, review binding and recovery payloads must match. The full production-offline suite and current browser suite are being checked before timing. Hosted no-op job measurement remains a separate open qualification in ct-x7vx; no production workflow will be started.

**2026-10-18T21:20:33Z**

Completed at measured candidate f525749 against f9f4499. Three alternating trials used identical inputs and runtime; all 269 payloads and published recovery bytes matched. Fresh publication: 3.388 → 3.642 seconds (+7.5%); unchanged poll: 0.207 → 0.098 seconds (−52.6%); resume: 2.701 → 1.664 seconds (−38.4%). Corrected checks: 9,072 Python tests plus 38 subtests, 152 JavaScript tests, 29 built pages, 2 bootstrap checks, and 54 comparison tests. Reviews and failures are retained. Report: docs/experiments/publication-remediation/combined-verification.md. Hosted-job observation remains ct-x7vx; no rollout.
