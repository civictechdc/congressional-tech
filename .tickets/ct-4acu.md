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


## Notes

**2026-11-10T14:08:12Z**

2026-11-10 14:03Z: lanes pass on the stack claude/ct-next-release c03c43da (document roles + recovery rule + name rule merged): six production-offline shards exit 0 and storage-loopback (full lane) exit 0; logs .cache/archive-release/lanes-ct-next-release-c03c43da/. First model-only build attempt stopped in 2 s on a missing local input (the worktree had no fetched spicy-regs tables); the spec now reads the nightly worktree's verified copy and the build is queued again.

**2026-11-10T14:45:20Z**

2026-11-10 14:39Z first full model-only build of the first stack (c03c43da: document roles + recovered-copy rule + name rule) on the exact inputs of 619db5f9e08e: release 597a6416a5c8, 305 steps, 902 s, peak 8.31 GiB RSS; .cache/archive-release/release-next/build-c03c43da/. Offline gate comparison (release-gate.json): 30 groups. Matches predictions: 18,032 renamed files (predicted 18,033), 1 removed document and 2 link keys (help page), 23 split rows and 26 URLs gone (recovered-copy rule, predicted 25/25). Not predicted at this size and sent to the model reviewer: document_kind changed on 16,342 and family on 5,811 (the official House kind vocabulary replaces the committee-name one: testimony -> witness-statement 7,658, etc.), meeting outcome changed on 14 and transcripts on 112, is_saved moved on 36,369 source rows, titles 1,230. Artifact of the runner, not the stack: retired_links empty and '452 keys vanish' because archive_model_job passes no retired-link ledger; later builds use release-next/bm_execute.py, which passes it as the publisher does.
