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
# Pin playwright-core for contract:archive and add explicit write-local-runtime helper in scripts/dev.py

Remove manual VIEWER_BENCHMARK_MODULES discovery for npm --prefix apps/site run contract:archive and provide an explicit command to generate a local-only DOCSPEC_JOB_CONFIG file while preserving cef-zrhq's no-implicit-default gate.

## Design

1. Pin playwright-core in apps/site/package.json devDependencies (matching the repo's installed Chromium headless shell revision) so npm --prefix apps/site run contract:archive resolves playwright-core from apps/site/node_modules without requiring VIEWER_BENCHMARK_MODULES.
2. Add a write-local-runtime subcommand to scripts/dev.py that writes a validated local-only runtime JSON (stripping remote and credentials keys) to a caller-specified path or .cache/docspec-catalog/runtime-local.json and prints the export DOCSPEC_JOB_CONFIG=... command, while keeping cef-zrhq's strict refusal when DOCSPEC_JOB_CONFIG is unset.

## Acceptance Criteria

- npm --prefix apps/site run contract:archive locates playwright-core without setting VIEWER_BENCHMARK_MODULES.
- python scripts/dev.py write-local-runtime produces a local runtime JSON that passes python scripts/dev.py doctor --lane production-offline.
- cef-zrhq regression tests continue to pass (missing DOCSPEC_JOB_CONFIG still fails fast before pytest).

