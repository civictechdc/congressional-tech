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
