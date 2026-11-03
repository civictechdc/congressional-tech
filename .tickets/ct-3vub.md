---
id: ct-3vub
status: closed
deps: []
links: [ct-77zb, cef-zrhq]
created: 2026-11-01T17:43:18Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [dx, testing, playwright, docspec]
---
# Pin playwright for contract:archive and add a verified local runtime helper to scripts/dev.py

Remove manual VIEWER_BENCHMARK_MODULES discovery and provide a checked way to create a local-only DOCSPEC_JOB_CONFIG. Reshaped after independent review: the scripts load playwright, not playwright-core; and stripping keys from a pipeline runtime fails doctor because the result has no pins and a different binary.

## Design

1. Exact devDependency playwright@1.64.1, with the composite action reading that one pin. The browser resolver tries local require first (archive-browser.mjs:5), so a differing site pin would silently override CI.
2. write-local-runtime takes --binary and --limits, verifies against load_runtime_pin and runtime_pin_digest, and writes absolute paths. Keep the cef-zrhq refusal when DOCSPEC_JOB_CONFIG is unset.

## Acceptance Criteria

- browserDependency("playwright") resolves without VIEWER_BENCHMARK_MODULES, tested directly, since contract:archive needs --next-release.
- A helper-written runtime passes scripts/dev.py doctor --lane production-offline; a wrong binary is refused.


## Notes

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
