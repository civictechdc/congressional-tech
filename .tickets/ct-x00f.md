---
id: ct-x00f
status: in_progress
deps: []
links: [ct-w564, ct-64t4, ct-i5u3, ct-0jgy]
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


## Notes

**2026-11-10T17:00:46Z**

2026-11-10 read-only triage of the red one line (evidence refactor/one-line/ol_*): the engine's hosted CI runs no Rust tests; it builds the release binary and runs the pipeline's production-offline lane in six shards (linux-release.yml:33,109-110), so dr-z0vd's '3 engine failures, 33 suspected environment failures' are pipeline tests on the one-line binary, never itemised; the names need the hosted run's log. 'Raw receipt writers require a clean application tree' is a workflow layout fault: the qualify job rewrites the tracked pin file in the pipeline checkout (linux-release.yml:90-96) and retention/writer_identity.py:15-16 refuses any uncommitted file; the checkout is also shallow while gate-5 tests resolve old commits. Hosted CI triggers only on main and fix/**, so the integration branch dx/one-line gets a CI run and a Linux binary only when pushed under a fix/ name. Predicted, not yet run: output bytes change on the one line (export and materialize take their schema from the optimized plan; scratch steps lost their row-group row cap), which would make an equal release id impossible by design; tested first by running one local job on both binaries. Memory fix into the one line: one conflict, one hunk, in Budget::create (keep both sides). Correction recorded for the owner: the one line's lake copy (managed jobs) asks for 64 KiB per request, one file at a time; a 7 November trial took 952 s for 488 MiB, so as built it is slower than the remote reads it replaces. Plan: PLAN.md sections 'Owner decisions and the one-line program' (O1 to O7, Q1 to Q6); managed-jobs decision paper: root-cause/MANAGED-JOBS.md.
