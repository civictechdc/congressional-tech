---
id: ct-b7bv
status: open
deps: []
links: []
created: 2026-11-10T13:27:30Z
type: chore
priority: 3
assignee: mikewolfd
tags: [ops]
---
# Housekeeping left from the 2026-11-10 release night

(1) .cache/archive-release/release-20261110/resume_publish.py is a guarded hand-resume wrapper that lives outside the repository; the driver now keeps a candidate across a commit that only records causes (0fad483d), which may make it unnecessary: either move it into scripts/ with a test or record that the driver replaces it. (2) Worktrees: wt/ct-document-roles, wt/ct-recovery-identity and wt/ct-name-rule are carried by the stack and can be pruned once the stack's lanes pass (the name-clash reader reads wt/ct-name-rule until it finishes); wt/ct-chc4-html-reader is in use by the body-text driver; wt/ct-thread1-unattended cannot be removed while Colima VM processes have it as working directory (do not restart Colima for this). (3) The shared heavy-job lock .cache/archive-release/heavy-slot.lock (a directory taken with mkdir) was introduced for four parallel builders; write it into docs/releases/2026-11-10-procedure.md or drop it when they finish. (4) Session-only scheduled checks do not survive an app restart: nothing durable watches the 05:30 nightly except its own summary.json.

## Acceptance Criteria

Each of the four items is done or declined with a reason.


## Notes

**2026-11-10T14:26:31Z**

2026-11-10 14:27Z: pruned seven builder worktrees whose work the second stack carries (ct-document-roles, ct-recovery-identity, ct-name-rule, ct-m878-fold, ct-9j3z-gate-facts, ct-name-clash-apply, ct-u9y4-records); their branches are kept until the stack is on main. Left: wt/ct-next-release (first stack; a model build is running from it), wt/ct-next-release-2 (second stack), wt/ct-chc4-html-reader (body-text driver), wt/ct-thread1-unattended (Colima).

**2026-11-10T14:52:36Z**

2026-11-10 14:52Z item 3 decided: the heavy-slot.lock directory lock is retired. Five docspec-rs survey answers named it as a cost (seconds-long jobs waited 6 to 30 minutes) and it duplicates the watchdog's admission by measured free memory. Heavy jobs run under scripts/archive_watchdog.py with an honest --expect-gb and --start-available-gb 6; the one remaining rule is nothing heavy while a real nightly_publish.py runs. The orchestrator's own queued builds still pass through the directory until they finish, then it is removed.

**2026-11-10T15:47:00Z**

2026-11-10: the PATH uv shim bit again: the engine's full check failed once in its Python stage because the pyenv shim picked uv 0.6.10 offline; it passed whole with /opt/homebrew/bin first on PATH (congress-1's engine builder). Any brief that runs an engine check needs that PATH line beside the pinned Rust toolchain.

**2026-11-10T16:26:15Z**

2026-11-10 16:26Z pruned on the owner's instruction ('Prune what is safe to do so'). CT: worktree wt/ct-next-release (the first stack, an ancestor of the second) and six branches whose every patch is in claude/ct-next-release-2: ct-next-release, ct-u9y4-records, ct-m878-fold, ct-9j3z-gate-facts, ct-9j3z-gate-fixes, ct-review-fixes (tips recorded in release-20261110/decisions-overnight.md). Engine: two idle, clean worktrees whose branches are on origin (docspec-ddk-runtime, docspec-spill-view-gc); branches kept. Deliberately kept: builder branches whose ticket notes or one conflict resolution differ from the stack by patch (ct-document-roles, ct-recovery-identity, ct-name-rule, ct-name-clash-apply) until the stack is on main; wt/ct-chc4-html-reader (the OCR driver runs from it); wt/ct-thread1-unattended (three Colima processes still have it as working directory); the build folders under release-next (5 GiB; the reviewers' evidence); engine worktrees with local-only or in-progress work (DataFusion 55, implicit-cast check, leaf-pushdown tests, the line-reconciliation plan, the one line) and their build folders (20 GiB, rebuildable, but not mine and possibly in use).

**2026-11-10T20:32:28Z**

2026-11-10 after release 77673bfb8fcf: 71 GiB free (124 this morning). Done: pruned worktrees wt/ct-release-b, ct-next-release-2, ct-next-release-3 and deleted the two oldest proof builds (release-next/build-c03c43da, build-final). Still held, with du sizes (APFS clones overstate): investigations 26 GiB (distinct-minmax-20261104 6.0, docspec-feedback-20261110 4.9, witness-agg-20261104 2.9, ct-3szv-maintenance 2.3, witness-key-map-20261104 1.6, thread-measure-20261110 1.6, r8-url-once-20261104 1.5), implementation 17, r1b-run 13, release-20261110 12 (fixes 6.6, two candidate clones 2.1 each), release-next 6.4 (build-main-control, build-final-2, build-final-3, build-release-b), handoffs 6.1, mcp-research-20261106 4.9, release-20261110b 4.3 (two clones of the published candidate; keep candidate-rebuilt as the base for the next release's comparisons), body-text 6.7, engine target folders about 17 (refactor team removes each as its branch merges). The 4 November investigations, implementation and r1b-run predate this week and need a named owner's look before deletion. The publisher's admission needs about 25 GiB, so tonight's nightly is not at risk.
