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

## Verification & Runtime Pins

- **docspec-rs revision**: `6e520c2c9941e802b4eda978d22fe8785c69c91e`
- **darwin-arm64 SHA-256**: `739020a1465f181e1e95019b13c107a9de81fa572d4f3599368561400eb88626` (236 MiB; registered in shared runtime store)
- **linux-amd64 SHA-256**: `aa52ccc78f206da51b58dfbed14851599ddb7c529f25ee7bf2c1f4c3a6973c7a` (`226,228,144` bytes; built & stripped in `Formspec-Labs/docspec-rs` run `46062254138`, artifact `15229583455`)
- **Immutable R2 key**: `runtime/docspec/6e520c2c9941e802b4eda978d22fe8785c69c91e/linux-amd64/aa52ccc78f206da51b58dfbed14851599ddb7c529f25ee7bf2c1f4c3a6973c7a/docspec` (bucket `congressional-tech-runtime`; upload pending `congressional-tech-runtime` R2 write credentials)
- **Qualification status**: Run `46062254138` (`linux-release.yml` against `feat/ct-bol5-docspec-pin`) succeeded in `build` and passed shards `1/6`, `3/6`, `4/6`, `6/6` (shards `2/6` and `5/6` failed only on Tesseract tests because `linux-release.yml` omits `tesseract: true`; full `6/6` with `tesseract: true` runs on the CT PR in `validate-explorer.yml`).

