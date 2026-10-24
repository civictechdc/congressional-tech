---
id: ct-tcfg
status: closed
deps: []
links: [ct-mi03]
created: 2026-10-20T20:37:00Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, testing, hygiene]
---
# Gate test-util-dependent integration tests and imports so bare cargo test --locked compiles cleanly

Running bare `cargo test --locked --no-run` (without `--all-features` or `--features test-util`) in `docspec-rs` fails to compile `tests/integration.rs` with:
- `error[E0599]: no method named update_until found for struct docspec::Engine` at `tests/authority.rs:41:14` (because `Engine::update_until` in `src/engine/update.rs:28-30` is gated on `#[cfg(feature = "test-util")]`, while `fence_preserves_selection_and_completions_and_reconciles_exact_retry` in `tests/authority.rs:23-24` is ungated).
- 7 unused-import warnings when `test-util` is disabled across `tests/rebuild.rs:11`, `tests/refresh.rs:7,8,16-18`, `tests/related_refresh.rs:15`, and `tests/schema.rs:11,16`.

## Design

Gate `tests/authority.rs` (or the `update_until` test inside it) and the `test-util`-only imports in `tests/rebuild.rs`, `tests/refresh.rs`, `tests/related_refresh.rs`, and `tests/schema.rs` with `#[cfg(feature = "test-util")]` so that both bare `cargo test --locked` and `cargo test --locked --all-features` compile and pass with zero warnings.

## Acceptance Criteria

- `CARGO_PROFILE_DEV_DEBUG=0 cargo test --locked --no-run` and `CARGO_PROFILE_DEV_DEBUG=0 cargo test --locked --test integration` succeed with 0 errors and 0 warnings.
- `CARGO_PROFILE_DEV_DEBUG=0 cargo test --locked --all-features --test integration` continues to run and pass `authority::fence_preserves_selection_and_completions_and_reconciles_exact_retry` and all other `test-util` fault-injection tests.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03b).
- Grades: proposal 94 → 94, work 83 → 83.
- Problem: Re-broke within a day (`a9515e5`, `tests/restore.rs`). `scripts/check` runs only `--all-features`, and there is no CI in docspec-rs, so nothing guards the acceptance criterion.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:31
- Covered by: the docspec-rs WS1 engine half (ss-pdv0 in spicy-stack), which adds an integration run without `--all-features` to `scripts/check`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
