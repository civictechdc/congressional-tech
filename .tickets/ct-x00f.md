---
id: ct-x00f
status: in_progress
deps: []
links: [ct-w564, ct-64t4, ct-i5u3]
created: 2026-11-10T16:38:56Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, pin, release]
---
# Qualify the one line with the memory fix as congressional-tech's next engine pin

Owner decision 2026-11-10 (relayed by the coordinator session): the pipeline's next engine is docspec-rs's one line (fix/docspec-one-line-20261109, f803ee6: the current pin plus the 18-commit DDK line) with the memory fix (fix/nested-slice-bytes) merged in; there is no separate memory-fix-only pin. The refactor team carries the engine's one-line plan (docs/line-reconciliation-20261108.md on codex/docspec-line-reconciliation-20261108; engine tickets dr-dlb1, dr-z0vd, dr-n3jx). Engine-side preparation starts now on our own integration branch dx/one-line (merges only; no existing engine branch is committed to or rewritten); everything that needs the pipeline's machine time or changes what the pipeline runs waits until the release in flight has shipped. First work item: the one line is red (dr-z0vd: CI run 42633258779, 3 engine failures and 33 suspected environment failures; its pipeline-qualify job failed with 'Raw receipt writers require a clean application tree'). Plan and status: .cache/archive-release/investigations/docspec-feedback-20261110/root-cause/PLAN.md. This ticket takes over the remainder of ct-w564's acceptance. Links ct-w564, ct-64t4, ct-i5u3.

## Acceptance Criteria

The engine's full check is green on the merged line (one line plus the final memory-fix tip), with the pinned toolchain. Mac and Linux binaries are built from that commit. The prefix run (scratch-sqlfix/sf-proof-dryrun-4) at the real limits (24 GiB, 2 threads) with the shared-budget debug log on passes against the pinned binary: no refusals; the lowest shared-budget available per step never near empty (floor set before the run); RSS under 14 GB; output hashes equal to the pinned binary's. Six production-offline shards and storage-loopback pass on the new binary. One full model-only identity build on pinned inputs gives a release id equal to the control's. The pin moves with disk budgets re-qualified in the same step (ct-ucwm). Outward steps (pushes, binaries into the store, uploads, the pin) are the coordinator's and the owner's.

