---
id: ct-mi03
status: in_progress
deps: []
links: [ct-2ukk, ct-czsd]
created: 2026-10-20T18:24:28Z
type: epic
priority: 1
assignee: mikewolfd
tags: [docspec, efficiency, debt]
---
# Reuse DocSpec execution and recovery instead of duplicating it

Reduce import staging, process and read-copy overhead while preserving source values, document identities, mappings, reviews and coherent application selection. Keep primary UI edits isolated. Local qualification and production adoption remain separate.

## Design & Ownership Contract

- **Native authority (`docspec-rs`)**: Owns admission, typed dataset versions, completion receipts, concurrency, and recovery. All five native worktrees are unified on `docspec-rs` `main` (`298053b`) and pushed to `Formspec-Labs/docspec-rs`.
- **Application authority (`congressional-tech`)**: Owns candidate identity, bounded typed preparation (`ct-adu0`), combined filesystem capacity preflight (`ct-n7la`), persistent loopback HTTP custody (`ct-q968`, `ct-copj`, `ct-bt1q`, `ct-3faj`), and coherent multi-table snapshot selection.
- **Evolutionary-refactoring guardrails**:
  1. Do not freeze or adopt a new `docspec-rs` binary (`ct-oxg6`) until the two P1 regressions introduced on `docspec-rs` `main` (`715a8c2`) are repaired: recursive nested export schema sanitization + primitive-leaf footer admission (`ct-3li2`) and restoring caller-bounded row-group sizing in `src/engine/write.rs` (`ct-cpio`).
  2. Retain unknown-outcome producer inputs whenever native worker state is indeterminate, including HTTP 422 `"worker"` / quarantine failures (`ct-3faj`).
  3. Commit and integrate the DuckDB external-sort (`ordered.parquet`) sequential-reader fix for `ct-adu0` from `docspec-typed-preparation` into `docspec-reuse-integration`.
  4. Consolidate remote R2 field-group capability checks (`ct-3180`, `ct-13cn`, `ct-dmca`, `ct-sb0s`, `ct-gziq`) behind one `Engine` boundary rather than scattering `group != "source"` checks across CLI, HTTP, export, and change-stream entry points.

## Acceptance Criteria

Measured before/after evidence, failure-path tests and independent review for each implemented child. Merge reviewed work and retain evidence before cleanup. Features without R2 support remain explicit dependent work; no unsupported operation is silently enabled.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit validated the epic architecture (grade B+ conditional) and unified `docspec-rs` onto `main` (`298053b`). Updated all child tickets to track: (1) P1 fixes required in `docspec-rs` before `ct-oxg6` binary freeze (`ct-3li2` at `src/engine/export.rs:639-641,864-930`; `ct-cpio` at `src/engine/write.rs:429-456` and `src/engine/export.rs:588-605`), (2) P2 producer-input retention on HTTP 422 `"worker"` errors (`ct-3faj` at `docspec.py:233-238` and `src/engine/http.rs:442-454`), (3) committing and integrating the uncommitted `ordered.parquet` sequential-reader fix in `docspec-typed-preparation` (`ct-adu0`), and (4) tracking `ct-wjce` in the central ticket set.
