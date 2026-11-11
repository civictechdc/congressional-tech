---
id: ct-07wr
status: closed
deps: []
links: [ct-6p6d, ct-w2kf]
created: 2026-11-10T16:39:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [model, performance, nightly]
---
# Model reads the lake table captures once: make it the first retained step

From the docspec-rs feedback root-cause analysis (cause A) and measurement M1 (.cache/archive-release/investigations/docspec-feedback-20261110/root-cause/PLAN.md, W10). In build c03c43da statements that read the lake table captures (12 files, 4.18M rows, about 206 MB) take about 345 of 895 s: it is scanned more than 40 times from the object store, about 10 s a scan, while a statement over one 4-million-row retained step takes 0.5 to 1.6 s. Change, pipeline only: in the full model job the lake captures is bound under another input name and the job's first step, named captures, is a materialized SELECT * of it; no model SQL file changes. Not for readings (its remote scans prune and cost about 2 s). Owner decision 2026-11-10: into the release in flight if the byte-identity proof passes. Branch claude/dx-captures-step. Replaces the engine cache of ct-w2kf on the pinned engine line. Links ct-6p6d, ct-w2kf.

## Acceptance Criteria

The submitted model job reads the lake captures in exactly one statement; fixture builds unchanged byte for byte; one model-only build through bm_make_spec.py and bm_execute.py on main's inputs for release 619db5f9e08e reproduces that release id; reported against the control build: total statement seconds, seconds in statements that read captures, peak RSS, where the retained step went and its size, margin under the 14 GB watchdog; six shards or a full lane; independent review.


## Notes

**2026-11-11T14:28:17Z**

validated 2026-11-11, closing: W10 is on main (4ab2ef18, merged with W12 as b12853f0 on the owner's 'Merge both now'). Code read on origin/main 17a283bc: archive_model.build_prepared_release binds the lake table as captures_input and its first step is 'captures' = SELECT * FROM captures_input, materialized (archive_model.py:1201-1227); no model SQL names captures_input. Post-merge evidence (decisions-overnight 23:48Z and 00:14Z): full lanes green on b12853f0; fixture before/after differences all explained by differing test inputs; the like-for-like pair on a quiet machine reproduces 77673bfb8fcf (release id, 32 files, 18 evidence, 31 queries) with statement seconds 778 -> 454, peak RSS 9.60 -> 11.48 GiB, margin under 14 GiB 4.4 -> 2.5 GiB; review in refactor/review-captures-step. The first production nightly with it (20261111T103005Z) rebuilt 77673bfb8fcf unchanged at 10.78 GiB RSS peak. The bm_make_spec.py/bm_execute.py route in the acceptance was retired in favour of archive_model_job --from-candidate (W3), which reproduced the release too.
