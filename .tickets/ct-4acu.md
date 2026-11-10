---
id: ct-4acu
status: closed
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

**2026-11-10T16:14:27Z**

2026-11-10 16:14Z release checklist additions. (1) ct-isnv on the stack changes apps/site and apps/explorer_mcp as well as the model: when the stack reaches main the Pages deploy carries the site change, and the Explorer MCP needs its own release for search_documents and the hearing bundle to read kind synonyms; the held text-search patch (investigations/review-fixes-20261110/rf_search_text_synonyms.patch) goes with a text-index pin update, not this release. (2) Release note lines owed: kind words changed with synonyms published in schema.json; recovery requirements (13 rows) as its own cause, 8 of 12 Wayback matches are spelling variants on an owner decision; meeting 101527 tied by title; event 101019 lists a July 10, 2013 transcript the House filed under June 20 (known source error); the first-schedule cap of 2,000 for the owner to overrule; two same-text Ways and Means reports split. (3) The release after this one: ct-kw85 Member appearances (claude/ct-member-appearances c98dab56, in review): 8,144 shown witness rows become member_appearance, coverage witness counts change on 931 meetings, 307 meetings go to empty with reason member_appearances_only; needs a site deploy and an Explorer release with it.

**2026-11-10T16:42:13Z**

2026-11-10 16:35Z the full stack (claude/ct-next-release-2 at 39131226: first stack + GovInfo fold-in + gate facts and their review fixes + MODS 35e24dae + reading-version equivalence + name-clash rules + model review fixes incl. kind synonyms) PASSES lanes: six production-offline shards exit 0 and storage-loopback (full lane) exit 0 (.cache/archive-release/lanes-ct-next-release-2-39131226/). The rebuild of record started 16:35:49Z (release-next/build-final-2, same pinned inputs and ledger as build-final).

**2026-11-10T17:03:57Z**

2026-11-10 16:51Z REBUILD OF RECORD for the stack at 39131226: release 2f6a6f9ae94c (release-next/build-final-2). Against the previous all-in build the only differences are the intended ones: changed titles 1,230 -> 1,168 (the 69 'H.R. ___' placeholder titles no longer appear) and schema.json now carries kind synonyms; all other 63 groups identical; link rule 0 missing, 0 dangling, 30 link keys and 38 lookup keys answer another file; the 93 corrected links verified by file identity; lost_landing_addresses 0, generic_titles 0. 16:59Z a third stack (claude/ct-next-release-3, 5df2e4c9 = the second stack plus the MODS asker rule, 11 commits; model_spec pin 26f1edc4 verified against publish-model.json's bytes; MODS fingerprint 63715237) started lanes; its build (release-next/build-final-3) follows with MODS rows from round-3/m11 (35,020 rows at the new fingerprint).

**2026-11-10T18:00:45Z**

2026-11-10 18:00Z owner decision: ship the rest now, hearing records (MODS) next. Release stack is now claude/ct-release-20261110b at cc7e64be (worktree wt/ct-release-b): 59 non-MODS commits of the earlier stack plus the recovery-requirements commit e84a92cf on its own; pin a5a2e3f136fa/5551 verified against publish-model.json. Lanes started 17:59:50Z (.cache/archive-release/lanes-ct-release-b-cc7e64be/); model build release-next/build-release-b follows. Earlier builds for reference only: build-final-2 (2f6a6f9ae94c, with MODS round 2) and build-final-3 (with MODS round 3). Next release: MODS (round 4 pending) with Member appearances (ct-kw85).

**2026-11-10T18:32:51Z**

2026-11-10 18:30Z the release stack claude/ct-release-20261110b at cc7e64be is TESTED: production-offline shards 2 to 6 exit 0 and storage-loopback (full lane) exit 0 in the first run; shard 1 exit 0 on rerun (its one failure in the first run was the known load timeout in house-naming, ct-cpd8). Logs: .cache/archive-release/lanes-ct-release-b-cc7e64be/ (shard-1.rerun.log). The model build (release-next/build-release-b) waited eight minutes for memory admission (about 13 to 14.6 GiB available; idle sessions' Flutter and Xcode tooling holds about 10 GiB) and was restarted with thresholds at its measured peak; running since about 18:33Z.

**2026-11-10T18:47:39Z**

2026-11-10 18:42Z RELEASE PROOF BUILD: claude/ct-release-20261110b at cc7e64be on the pinned inputs of 619db5f9e08e plus the ct-u9y4 corrections gives release 8aa4f840c41b (release-next/build-release-b; 601 s, 9.63 GiB peak physical). Against the earlier build of record it differs only by the hearing-records effects being gone (22 groups: all witnesses groups, the CHRG-113hhrg85898 / meeting 101527 effects); 43 groups remain against the live release: documents 357,471 -> 322,696 (34,827 removed, 24 added, 28 split), link keys 442,109 -> 407,305 with all 34,828 removed keys retired (retired 450 -> 35,278), link rule 0 missing / 0 dangling / 30 link keys and 38 lookup keys answer another file, renames 18,185, kinds 16,484, families 5,965, titles 1,168, 14 meeting outcomes, 112 transcripts, recoveries 12,632 -> 12,587, 13 url_state capture decisions (recovery requirements), schema.json and capture_profile.json changed; witnesses unchanged (172,435). The 93 corrected links verify by file identity; lost_landing_addresses 0, generic_titles 0, unplaced_landing_pages 2. The stack touches no guarded resource path (engine pin, limits, archive-jobs, uv.lock, package-lock), so disk budgets stand. Refactor team released to use the machine (captures proof first).

**2026-11-10T20:39:17Z**

2026-11-10 RELEASED, closed. Release 77673bfb8fcf published 2026-11-10T20:27:52Z over 619db5f9e08e (run nightly/20261110T202340.237447Z, exit 0); release note docs/releases/2026-11-10-77673bfb8fcf.md (e04d58bd); reviewed cause record model/jobs/release-causes/619db5f9e08e-77673bfb8fcf.json (78 groups: 67 explained, 11 accepted defects; 68 named corrections). Each line below was checked on the published tables, not on notes.
SHIPPED: help page as a wrapper (ct-aoxp, closed); GovInfo details pages folded into their hearings: 34,826 fewer documents, 34,824 addresses kept, 35,278 retired keys (ct-m878, closed; owner questions to ct-egoo); junk link-text titles gone (ct-ccsi, closed); official House names with committee names winning slot clashes, and the 343 clash decisions (ct-h8dr, open for 25 unread clashes and 1 unmet decision); the 54 testimonies back under committee names (ct-yuf0, closed); recovered-copy rule plus the 69 rejections and 24 re-recorded files: Bowman two rows, no unrelated documents fused (ct-u9y4, open for the 83 page-plus-file rows, 18 editions, 3 recordings, and a refusing check); url_state.recheck_meeting_date and linked_from (ct-9j3z, open until a real night proves it); named corrections in the gate, used for 30 + 38 keys (ct-4nax, closed); witness-statement/testimony synonym in schema.json (ct-isnv); recovery requirements 1 -> 14 rows, 13 url_state rows (ct-l7uh, ct-umtm); the day's Mac capture and meetings relist (392 + 24 new documents; ct-4jms, ct-q4e2).
MOVED TO THE NEXT RELEASE: hearing-record (MODS) parsing round 4 with Member appearances (ct-kw85, on its branch, not on main yet; ct-zs48, ct-3aap); the model reading captures once (ct-07wr).
OPEN FOLLOW-UPS: ct-isnv (widened: amendment, opening-statement, transcript, committee-report still lose under exact filters), ct-m3h3 (two same-text Ways and Means reports split), ct-fk4w (settle name clashes by reading the PDF), ct-jcnd (placeholder and Download titles, unmet decision), ct-uywf (relist re-keys witnesses), ct-zdj8 (recordings not traceable), ct-dagf and ct-faan (named-correction follow-ups), ct-v8us (530 outcome references still renumbered), ct-egoo, ct-xj8s.
