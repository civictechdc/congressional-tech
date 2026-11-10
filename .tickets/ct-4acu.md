---
id: ct-4acu
status: open
deps: []
links: [ct-w564]
created: 2026-11-10T13:27:30Z
type: task
priority: 1
assignee: mikewolfd
tags: [release]
---
# Next release after 619db5f9e08e: stack, full build, one review, owner approval

Branch claude/ct-next-release (worktree /Users/mikewolfd/Work/wt/ct-next-release) = main + document roles (ct-aoxp, ct-ccsi) + recovery identity (ct-u9y4 rule) + name rule (ct-h8dr, ct-yuf0). To join: the MODS branch claude/ct-mods-zs48-3aap when its tip stops moving (owner: ships in this release under one review), ct-m878 fold-in, ct-9j3z gate facts, ct-u9y4 record corrections, the per-document decisions on the 343 name clashes. Not gating: the engine fix and re-pin (its own change). None of the branches has had a full model build; the three stacked ones each passed six shards plus storage-loopback separately but have not been run merged. The reading-version edit on the MODS branch must be reconciled with main's 0.84.0 html_text and warc bump.

## Acceptance Criteria

Six shards and storage-loopback pass on the stack. A full model build outside the driver produces a candidate; the gate's differences against 619db5f9e08e are each explained by a named change, with a reviewed cause record where the gate asks for one. One independent review covers the whole stack. The owner approves before anything is published. Release note written.

