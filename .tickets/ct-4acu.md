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

**2026-11-10T15:22:16Z**

2026-11-10 15:12Z second stack (claude/ct-next-release-2: first stack + GovInfo fold-in + gate facts + MODS 35e24dae + name-clash rules) passes lanes: six production-offline shards exit 0 and storage-loopback (full lane) exit 0 (.cache/archive-release/lanes-ct-next-release-2-16ecef9b/; the tree under test was 9cec1787). 374b9f56 (reading-version equivalence) added after, doctor passes with the one readings warning main has, its two test files pass; tip 7da554ca. 15:19Z CONTROL BUILD PASSES: main's SQL on the exact inputs and ledger of the published release, through the hand-built spec and bm_execute.py, gives release id 619db5f9e08e813aa3ba474435cf9d158bd9eba9bdd14d2e619f55ee5b3cbfc0, identical to the live release (877 s, peak 8.19 GiB). So differences shown by the other model-only builds are the stack's. All-in build started (release-next/build-final): stack tip 7da554ca, ledger from 619db5f9e08e, captures + 24 corrected rows (4,176,171), filename readings + 24 (1,410,200), the 69-rejection file, appearance rows = pinned snapshot's three other sources + 35,020 MODS rows re-parsed at e599dff6. Not yet in it: the review-fix and gate-fix builders' commits, and the MODS asker rule; it is rebuilt when they land.

**2026-11-10T15:40:24Z**

2026-11-10 15:38Z ALL-IN BUILD built: release 6b6929212977 from stack tip 7da554ca with the retired-link ledger, the ct-u9y4 corrected inputs and MODS rows at e599dff6 (.cache/archive-release/release-next/build-final/; 882 s, peak 9.16 GiB). Against 619db5f9e08e: documents 357,471 -> 322,696 (34,827 removed = 34,826 GovInfo details pages + the help page; 24 added; 28 split); link keys 442,109 -> 407,305, every removed key retired (retired 450 -> 35,278), link rule: 0 keys vanish, 0 dangle; 30 link keys and 38 lookup keys answer another file (the record correction); renames 18,185; kinds 16,484; families 5,965; titles 1,230; recoveries 12,632 -> 12,587; witnesses 65 added and 125 types changed (MODS); 15 meeting outcomes. The 93 corrected links checked by file identity: all present, each shows the expected file, own recovery-only row, no rejected file left (the builder's rr_21 checker compares release-local row numbers and cannot be used on a build that renumbers rows). Sent to the model reviewer to reconcile every group with its expected list; open items: one document whose meeting, committee and date changed, 13 url_state capture decisions, the 15th outcome.

**2026-11-10T15:49:06Z**

2026-11-10 15:47Z the model reviewer reconciled the all-in build (6b6929212977) against the live release group by group: all 65 gate groups trace to a named rule or input, documents matched by link key; NO DEFECT. Arithmetic: 357,471 - 34,827 (34,826 details pages + help page) + 52 (28 split + 24 added) = 322,696 documents; link keys 442,109 - 34,828 + 24 = 407,305; retired 450 + 34,828 = 35,278; recoveries 12,632 - 69 + 24 = 12,587; all 18,187 expected renames happen with exactly the predicted names; titles the same 1,230 rows; 38 changed lookup keys = effect-A's 30 plus their 8 alias keys. Items I could not attribute, now explained: the one document whose meeting changed is CHRG-113hhrg85898, tied by the MODS re-parse to meeting 101527 (correct; it is also the 15th outcome and 113th transcript); 13 url_state capture decisions come from commit c71f1a4a (the recovery-requirements input grows from 1 row to 14), which no reviewer covered: asked congress-1. Accepted and noted: the recovered-copy rule splits 2 same-text Ways and Means report PDFs (rows 334942, 335064) that are really one document each. Report: investigations/next-release-review-20261110/model/REVIEW.md, 'All-in build reconciliation'.
