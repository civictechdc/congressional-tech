---
id: ct-3vub
status: open
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

