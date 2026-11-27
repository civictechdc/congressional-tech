---
id: ct-bol5
status: open
deps: []
links: []
created: 2026-11-25T20:29:35Z
type: task
priority: 1
assignee: mikewolfd
tags: [ddk-migration, docspec, runtime]
---
# Upgrade docspec-rs runtime pin to external-overlay release for DDK readiness

Advance `model/docspec-runtime-pin.json` from `98a2d540` to a DDK-aligned `docspec-rs` release (`6e520c2` / external-observed lake overlay + Wave 4.1 fixes) and register pinned platform binaries in the shared runtime store without changing published archive semantics. Keeps archive builds on the latest bounded-memory query engine and lets `spicycongress` mount the 4.15M-row capture/archive lake zero-copy via `observe_external_parquet` before migrating individual SQL steps.

## Design

Update `model/docspec-runtime-pin.json` (`source_revision`, `required_capabilities`, `platforms.<platform>.sha256`), verify `scripts/dev.py write-local-runtime` + `doctor`, and prove exact parity on archive-model outputs plus a zero-copy `inspect-external` / `observe_external_parquet` smoke check. Non-goal: do not rewrite `model/sql/*.sql` or touch byte-hashed parser files.

## Acceptance Criteria

(1) `model/docspec-runtime-pin.json` pins a `docspec-rs` commit containing external-observed lake overlays (`f4d427c`/`6e520c2` or newer) with verified `darwin-arm64` and `linux-amd64` SHA-256 digests. (2) Local `doctor`, full native lake/model test lane (`exit 0`), and all 6 model invariant suites pass with exact release parity. (3) Smoke check confirms `spicycongress` (`observe_external_parquet` / `docspec inspect-external`) mounts a sealed archive Parquet output zero-copy without copying or re-materializing the 4.15M-row `captures` lake.

