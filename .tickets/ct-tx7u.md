---
id: ct-tx7u
status: open
deps: []
links: [ct-exlx]
created: 2026-11-11T11:45:37Z
type: bug
priority: 2
assignee: mikewolfd
tags: [lake, schema, field-ids]
---
# The declared lake schemas for captures and readings state field ids the real tables do not have

Found 2026-11-11 by the pin comparison's builder (refactor/one-line/ol_pin_compare_selftest_pass.txt, under .cache/archive-release/investigations/docspec-feedback-20261110/) and traced read-only by the W3 builder. model/lake/captures.schema.json and model/lake/readings.schema.json declare field ids that no created table carries. The engine's create operation (congress_api.lake.tables.create_table, kind 'create') assigns fresh ids, whatever ids the JSON states: positional at the top level, then each list's element and each struct's fields. The test lakes are made from the same files by the same call (archive_job_fixture.native_daily_spec, lines 173-175), so they carry the fresh ids. So do the real tables. The real captures table (uuid 01a1a35c..., created 2026-11-03T21:41:53Z by its UUIDv7) was created a day after the last change to the declared file (bdcde68e, 2026-11-02T16:16:33Z), and CT has no schema-evolution operation (only create_namespace, create, append, purge, resolve). Files the pinned engine built from the real lake for release 77673bfb8fcf already carry the fresh ids on lake-copied columns. In capture_evidence.parquet, 38 of the 39 captures columns carry ids: all 38 equal the fresh ids and 17 equal the declared ones (intact carries none). page_facts.parquet carries the readings nested ids 21, 32, 33 and 34.

Exact ids, declared -> created. captures (same 39 columns, 18 agree): context_url 14->10, member_path 15->11, original_path 42->12, h_content_disposition 17->13, attempt 38->14, http_status 11->15, complete 13->16, fetch_http_status 39->17, fetch_outcome 40->18, expansion 16->27, stored_suffix 27->28, stored_md5 28->30, recovery_category 30->31, original_url 31->32, recovered_url 32->33, match_basis 33->34, evidence_sha256 34->35, imported_at 35->36, writer_job 36->37, writer_commit 37->38, mapping_version 41->39. readings: the 20 top-level ids agree and the 14 nested ids differ: named_meetings.element 101->21, links.element 102->22, links.element.href to .remove_date 110-118->23-31, fields.element 103->32, fields.element.field 120->33, fields.element.value 121->34. filename_readings: all 26 agree.

Published columns affected: in_archive_since (detail.parquet, document_rows.parquet), copied from captures imported_at, carries 36 (declared 35); source_url (source_members.parquet), copied from captures original_url, carries 32 (declared 31). The published recoveries.parquet already carries imported_at 36 on the pinned engine. On the one-line pin (ct-x00f) more published columns carry lake ids (owner: 'Accept them', ct-exlx). They are the tables' real ids, so the pin's byte test must expect 36 and 32, not the declared 35 and 31.

Where the declared schemas are used. To create tables (the declared ids are passed in and replaced): captures in cli/captures_ingest.py:263-266, lake/capture_backfill.py:331-333, viewer_publication/archive_selective.py:305 (local catalog) and the test fixture above; readings in lake/readings.py:721-726, whose partition spec names source ids 2 and 3 (parser, parser_version), which are positional and so kept by create; filename_readings in lake/filenames/__init__.py:290; the record tables through lake/_record_producer.create_record_table. For names, types and required flags only (ids not read): lake/tables.py (LAKE_SCHEMA_PATHS, TABLE_SPECS, load_schema, table_spec), lake/capture_backfill_guard.py:56 (required columns), lake/compatible_proof.py:346, archive_selective.py:139 and 357, lake/reading_version_diagnostics.py:15. In the model's identity: every model/lake/*.json is hashed into the model definition (archive_model_profile._definition_hashes, line 90) and the profile's lake_versions (archive_model.py:1167), so correcting the ids changes those hashes. No CT code compares declared ids with a table's; identifier-field-ids are [1,2,3] in all three files, positional and unaffected. Outside the repository, the pin comparison script reads column names from the declared files and cross-checks ids.

Check (the coordinator's; read-only on R2; written, not run): refactor/pin-move/real-captures-schema-check.txt. It fetches the three tables' metadata objects at release 77673bfb8fcf's pins with congress_shared.storage.connect_r2 (R2 keys from the environment; no credentials file opened) using refactor/model-build/mb_fetch_lake_metadata.py, then compares their ids with the declared files using refactor/model-build/mb_lake_ids.py. Expected from the local evidence: captures 18 of 39 equal, readings 20 of 34, filename_readings 26 of 26.

## Acceptance Criteria

The declared captures and readings schemas state the ids the tables actually have: the created ids, confirmed by the check or a local create. A test creates each declared lake table on a local catalog and asserts that the created schema's ids equal the declared ones (it fails today for captures and readings). The model-definition hash change is recorded with the reason. The pin's byte test takes lake ids from the tables, not from the declared files. The other declared lake schemas (meeting, appearance, video, committee and playlist records, body text) are checked the same way.


## Notes

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: the check ran (decisions-overnight 11:46Z, three read-only GetObjects at 77673bfb8fcf's pins: captures 18 of 39 ids equal the declared file, readings 20 of 34, filename_readings 26 of 26, as predicted), so the premise is confirmed. Not fixed: model/lake/captures.schema.json still declares context_url 14, original_url 31, imported_at 35 (created ids are 10, 32, 36). Remains: correct the declared ids, the create-and-compare test for every declared lake table, and the recorded model-definition hash change.
