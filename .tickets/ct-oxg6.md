---
id: ct-oxg6
status: open
deps: [ct-copj, ct-bt1q, ct-3faj, ct-q968, ct-3li2, ct-cpio, ct-xl0y]
links: []
created: 2026-10-20T18:47:06Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, qualification]
---
# Qualify the new native host without changing retained migration state

Persistent transport requires native request deadlines (`request-deadline`) and owned-pipe EOF draining (`owned-stdin-eof`). Freeze a reviewed `docspec-rs` binary from `main` **after** the P1 fixes in `ct-3li2` and `ct-cpio` land, and qualify a separate application runtime; preserve the existing production binary, credentials, workspace, failed operation and production selectors.

## Acceptance Criteria

- **Pre-freeze gate**: `ct-3li2` (recursive nested export sanitization + primitive-leaf footer admission) and `ct-cpio` (caller `Limits` row-group compliance + removal of hardcoded `news_lake` column names) must be committed and passing on `docspec-rs` `main` before building the candidate binary.
- Record the exact `docspec-rs` `main` commit SHA and frozen binary SHA-256 digest; verify `docspec-loopback` protocol v1 capabilities (`request-deadline`, `owned-stdin-eof`), remote `source` comparison (`ct-3180`), and unused-key-registration removal (`ct-xl0y`) in one unified binary.
- Test required host capabilities, `SIGKILL` owner-loss draining (`ct-bt1q`), unknown-outcome producer retention (`ct-3faj`), and exact-version streaming reads (`ct-q968`) through the new runtime; integrate dependency documentation and startup error diagnostics.
- No production import restart or config replacement; retain existing operation recovery prerequisites.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit updated `deps` to include `ct-bt1q`, `ct-3faj`, `ct-3li2`, `ct-cpio`, and `ct-xl0y`. Now that `docspec-rs` branches are unified on `main` (`298053b`), fixing `ct-3li2` and `ct-cpio` on `main` will allow freezing one authoritative candidate binary instead of the separate per-worktree binaries (`f6699cd6`, `718c95bc`, `20a9fd82`).
