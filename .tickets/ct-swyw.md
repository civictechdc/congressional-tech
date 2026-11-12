---
id: ct-swyw
status: closed
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


## Notes

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: not done. packages/viewer_publication/tests/test_phase1_model_repeat_cost.py:201 LAKE_TABLES still omits playlist_records and the docstring's seven-of-eight paragraph (lines 34-39) is still there; no local-lake build with playlist_records has been made.

**2026-11-12T06:00:00Z**

Closed on `claude/ct-wave-1ab-safety`:
1. Updated `scripts/measure/model_relation_rows.py` (with unit tests in `scripts/tests/test_model_relation_rows.py`) to:
   - Read newer `archive-model/job.json` layouts alongside legacy `model-scratch/job.json`.
   - Accept `--lake-metadata DIR` for builds whose `native_table` inputs pin remote `s3://` snapshots, decompressing gzip `.metadata.json` files and failing closed unless `table-uuid`, `schema-id`, and `snapshot-id` match the pin in `job.json`.
   - Map `spicy-regs` manifest rows under both `<name>` and `spicy_<name>`, and resolve cleaned `.archive-model-inputs-*` / retired-worktree `model/...` pins only when `size` and `sha256` match `model-spec.json`.
2. Regenerated `packages/viewer_publication/tests/fixtures/model-relation-rows.json` from the watched heavy-slot pinned-engine (`ae12bbd`, commit `f81c9cf1`, peak `9.313 GiB` RSS / `10.781 GiB` physical) corpus build `.cache/archive-release/investigations/docspec-feedback-20261110/refactor/pin-move/candidate-build-2` and its 8 fetched Iceberg metadata files in `real-lake-metadata-2` with `--overlay-registries` for the 3 registries committed on `main` after `candidate-build-2` (`recovered_file_roles = 146`, `title_overrides = 0`, `title_rules = 9`; `278 -> 341` relations, `0` removed, `playlist_records = 4,362`, `selected_playlist_records = 4,362`).
3. Bound `playlist_records` (`8/8` lake inputs) and `playlist_records.current_versions()` in `packages/viewer_publication/tests/test_phase1_model_repeat_cost.py` (`selected_playlist_records` now plans two direct lake scans over the created `playlist_records` table instead of the `PLAYLIST_RECORDS_UNAVAILABLE` NULL-literal stand-in), removed the seven-of-eight docstring paragraph, and asserted all 8 lake inputs are bound with zero physical-plan refusals.
4. Re-recorded `REPEAT_COST_TRACKED` and `OUTER_BUILD_TRACKED` from the new 338-relation measurement and verified every movement:
   - **`REPEAT_COST_TRACKED` (same 12 readers, 0 added, 0 removed):**
     - `entity_profile_completeness`: `49,033,171 -> 52,486,704` (`captures` `4.15M -> 4.18M`, `readings` `1.42M -> 1.65M`, `appearance_records_input` `66,490 -> 362,679` with MODS, `meeting_records_input` `24,431 -> 48,804`).
     - `model_invariants`: `50,877,106 -> 50,844,619` (`document_identities`/`document_members`/`source_annotations` corpus growth offset by `ordered` `355,608 -> 323,087`, `recording_tracks` `2.80M -> 773`, and `document_bill_decisions` directly measured at `1` instead of largest-input fallback).
     - `merged_recovery_fields`: `43,005,605 -> 43,910,562` (`document_members`/`source_annotations` `2.06M -> 2.12M`, `document_identities` `1.83M -> 1.89M`, `source_rows` `569K -> 583K`).
     - `component_meeting_links`: `32,189,482 -> 32,795,656` (`effective_filenames` `4.14M -> 4.17M`, `source_annotations`/`source_files` `2.06M -> 2.12M`).
     - `bills_export`: `33,468,701 -> 32,624,273` (`ordered` `355,608 -> 323,087` x26 extra).
     - `retired_links_export`: `32,708,507 -> 30,804,350` (`prior_links` `440,340 -> 407,698` x20 extra, `ordered`/`details` `355,608 -> 323,087`, including `ct-egoo`'s `+906,198` from reading `source_rows` and `details` once more).
     - `profile_completeness`: `23,295,486 -> 26,698,918` (`readings` `1,416,679 -> 1,654,201` x14 extra with `html_metadata` readings).
     - `model_url_keys`: `18,289,579 -> 18,746,431` (`url_normalized`/`url_inputs` `1.66M -> 1.70M`).
     - `pinned_readings` & `link_inputs`: `14,177,632 -> 16,552,860` (`readings` `1.42M -> 1.65M` x10 extra).
     - `source_url_keys`: `13,842,862 -> 14,165,195` (`source_url_normalized`/`source_url_inputs` `1.26M -> 1.29M`).
     - `publisher_links`: `11,093,345 -> 11,536,883` (`resolved_links` `6.11M -> 6.42M`, `model_url_keys` `1.66M -> 1.70M`).
   - **`OUTER_BUILD_TRACKED` (5 removed below `100,000` once directly measured, 1 added above `100,000` once `playlist_records` / `caption_resource_requests` is measured):**
     - Removed `recording_tracks` (`1 -> 0`): `recording_track_candidates` moved from `2,803,504` down to `43,343` rows (`< 100K`).
     - Removed `page_dates` (`1 -> 0`), `document_page_metadata` (`7 -> 0`), `page_descriptions` (`4 -> 0`), and `document_page_metadata_entries` (`5 -> 0`): `page_metadata_values` (`55,096`), `page_metadata_documents` (`14,868`), and `html_metadata_readings` (`14,783`) were unmeasured in Nov 4 `build-1` (falling back to `readings = 1.4M` or `base_normalized = 356K`) and are all `< 100K` when directly measured.
     - Added `caption_resources` (`None -> 1`): `caption_resource_requests` (fed by `selected_playlist_records`) was unmeasured in Nov 4 `build-1` and is now directly measured at `454,524` rows (`>= 100K`, 9 columns).
5. Verified `packages/viewer_publication/tests/test_phase1_model_repeat_cost.py`, `scripts/tests/test_model_relation_rows.py`, and `.github/tests/test_offline_shards.py` (`53 passed in 10.86s`, peak `0.50 GiB` RSS under `archive_watchdog.py`).
