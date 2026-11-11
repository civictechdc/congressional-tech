---
id: ct-swyw
status: open
deps: []
links: [ct-exlx]
created: 2026-11-11T03:32:27Z
type: task
priority: 2
assignee: mikewolfd
tags: [model, tests, lake]
---
# Plan pass: bind playlist_records to an empty lake table too (seven of eight lake inputs today)

test_phase1_model_repeat_cost.py (W6, branch claude/dx-lake-backed-plan-pass) plans every model reader over empty local lake tables, so a lake-only physical-plan refusal (ct-h8dr: coalesce(f.valid,false) in saved_name_conflicts failed 26 lane tests) fails the pass in seconds instead of a 20-minute lane. It binds seven of the eight lake inputs of model/jobs/publish-model.json. playlist_records is not bound, so its readers plan over archive_model.py's PLAYLIST_RECORDS_UNAVAILABLE stand-in step of NULL literals: nullable where model/lake/playlist-records.schema.json requires 6 of 7 fields, and without field ids, so a lake-only refusal there is not seen. Binding it needs a measured playlist_records row in packages/viewer_publication/tests/fixtures/model-relation-rows.json, never a hand-written one: selected-records.sql scans its input twice, so the repeat-cost score reads that row. The fixture's rows come from one local-lake build (.cache/archive-release/investigations/witness-agg-20261104/runs/build-1), which predates playlist_records; newer builds that have it (for example refactor/model-build/control-77673bfb in the docspec-feedback-20261110 investigation) pin remote s3:// snapshots, which scripts/measure/model_relation_rows.py cannot count (it reads each pin's metadata file locally). Parquet stand-ins cannot stand in: the pinned engine strips field metadata from a Parquet input (engine ticket def-9ise; CT side ct-exlx).

## Acceptance Criteria

One local-lake model build with a playlist_records input, on the heavy slot under the watchdog; scripts/measure/model_relation_rows.py over it regenerates fixtures/model-relation-rows.json (check its layout assumption: it reads model-scratch/job.json, newer builds keep archive-model/job.json). Every tracked figure in test_phase1_model_repeat_cost.py (REPEAT_COST_TRACKED, OUTER_BUILD_TRACKED) re-recorded from the new rows, each change explained. playlist_records added to LAKE_TABLES and its pinned parser version to submitted_job; the module docstring's seven-of-eight paragraph removed. The pass green (partial), then a lane.

