---
id: ct-q05l
status: closed
deps: [ct-oxg6]
links: [ct-sb0s, ct-13cn, ct-3180, ct-dmca, ct-gziq]
created: 2026-10-20T23:52:13Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, r2, refactoring]
---
# Consolidate remote R2 operation and field-group capability checks into one Engine authority

Epic ct-mi03 guardrail #4 and CS 300 review notes on ct-dmca, ct-sb0s, ct-gziq, ct-13cn, and ct-3180 identify structural erosion in how docspec-rs gates remote (R2) operations: capability checks are scattered across Engine::require_local, check_backend_selection, and check_request_backend (src/engine.rs:358-404), CLI argument checks (src/main.rs:514-540,653-685), HTTP handlers (src/http.rs), change streams (src/engine/changes.rs:48-137), backfills (src/engine/backfill.rs), input capture (src/engine/inputs.rs:163-165), and compaction (src/engine/compaction.rs:107-112).

## Acceptance Criteria

- Introduce one authoritative capability check in docspec-rs (src/engine.rs) that decides whether a given operation and field group (source vs computed/related/evidence) is supported on the configured backend (Local vs Remote R2).
- Route CLI, HTTP, comparison/change-stream, backfill, refresh, receipt, input-capture, and maintenance entry points through that single Engine authority, preserving exact error codes (remote_scope / unsupported_backend) and refusal semantics.
- Verify with existing local and remote_cli test suites before extending R2 support in ct-dmca, ct-sb0s, ct-gziq, and ct-13cn.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to enforce ct-mi03 Guardrail #4 (single Engine authority for remote R2 operation and field-group capability checks across src/engine.rs:358-404, src/main.rs, src/http.rs, src/engine/changes.rs) before ct-dmca, ct-sb0s, ct-gziq, and ct-13cn.

**2026-10-21T00:31:34Z**

Implemented: added public BackendCapability { SourceGroup, LocalOnly } in src/engine.rs with for_group/local_only; Engine::supports_capability/require_capability/require_group is now the single authority. read_group, compare_with_options, changes, export, require_local, and the CLI preflight route through it. cargo check --all-features and cargo test --lib 367 pass; integration 323 pass.

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fix -> Grade: A. Routed the remaining export_admitted group check (docspec-rs/src/engine/export.rs:501-505) through BackendCapability::for_group(&policy.group).local_only().
