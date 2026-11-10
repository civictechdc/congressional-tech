---
id: ct-8m0e
status: open
deps: []
links: [ct-x00f]
created: 2026-11-10T18:08:24Z
type: task
priority: 2
assignee: mikewolfd
tags: [model, schema, engine-pin]
---
# Keep six published 'required' flags across the one-line engine pin: respell coalesce(<boolean>, false)

The engine's one line writes output schemas from the optimized plan (ct-x00f). Six published flags would change from required to optional although the columns hold no nulls: hidden in list, detail and document_rows (packages/viewer_publication/src/viewer_publication/archive_model.py:1167, coalesce(r.hidden,false)); is_real_file in record_roles and capture_sources (model/sql/record-roles.sql:54); filename_date_eligible in source_filename_readings (model/sql/source-annotations-filename.sql:82, a CASE of two such coalesces). Cause: the optimizer rewrites coalesce(b, false) to 'b IS NOT NULL AND b', never null but typed nullable. Measured on a copy of a fixture model job with 45 outputs (evidence .cache/archive-release/investigations/docspec-feedback-20261110/refactor/one-line/ol_null_probe*, ol_respell_*.json, ol_patch_keep_required.py): spelled 'b IS TRUE' (IS TRUE around the whole CASE for the third; inside each branch it does not work) the columns stay required on the one line with equal values for true, false and NULL, and on the PINNED engine the respelled job writes 45 of 45 files byte-identical to today's. Spellings that do NOT keep the flag: ifnull(b,false), CASE WHEN b THEN true ELSE false END, b IS NOT DISTINCT FROM true. WARNING from this week's history (the name-rule builder's survey answer, name-rule.md in the feedback folder): on LAKE-BACKED inputs coalesce(f.valid,false) failed physical planning on field-id metadata in a common subexpression (step saved_name_conflicts), 'IS TRUE then failed on nullability', and that change settled on IS NOT DISTINCT FROM true. The fixture job above has no lake-backed inputs, and source_filename_readings reads a lake table. So the spelling must be proven on lake-backed inputs before it is chosen, per step. Approved by the coordinator 2026-11-10: after the release in flight, before the one-line pin. Links ct-x00f.

## Acceptance Criteria

A contract test that the six columns are marked required in their published files (it passes on today's engine before and after; its job is to fail if the one line is pinned without this change). The three expressions respelled; for each, the spelling used and why, after reading why IS TRUE failed for the name-rule change; if IS TRUE does not plan on a lake-backed step, the spelling that both plans there and stays non-null under the optimized plan. Proof on lake-backed inputs: packages/viewer_publication/tests/test_archive_selective.py and test_archive_publish_job.py pass; one full model-only identity build on pinned inputs through bm_make_spec.py and bm_execute.py gives the control's release id AND all 18 evidence files equal on the pinned engine. Fixture outputs byte-identical before and after on the pinned engine. On the one-line binary (run through its command line on a retained job, no pin edit): the six flags stay required. Independent review; one full lane or all six shards.

