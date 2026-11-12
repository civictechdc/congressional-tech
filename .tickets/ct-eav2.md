---
id: ct-eav2
status: closed
deps: []
links: [ct-ucwm, ct-h267]
created: 2026-11-11T09:47:37Z
type: bug
priority: 2
assignee: mikewolfd
tags: [backfill, lake, safety]
---
# A backfill must check the target table's schema before any write or fetch

Found 2026-11-11 while planning the MODS appearance activation (.cache/archive-release/investigations/mods-backfill-activation-20261111/ba-findings.md). The backfill job's default mode (daily.py:903, appearance stage :1100-1117) writes owed producer records to R2 (daily.py:942 -> :512) and fetches every body to re-stamp (35,020 MODS bodies here) before the append to the existing lake table, and the pinned engine refuses that append when the new rows carry columns the table lacks (schema_mismatch, docspec-rs src/storage/batch.rs align_native_batch; reproduced locally by .cache/archive-release/investigations/mods-backfill-activation-20261111/ba-schema-probe.py). So a schema change fails only after side effects and a long fetch. Also: --plan is not a dry run (archive_backfill_job.py:169 echoes the spec and reads no data), and the backfill binding had no disk-budget entry.

## Acceptance Criteria

Before any producer-record write or body fetch, the job compares the rows it would append with the target table's schema through the engine and refuses with a clear message naming the missing fields; a test plants a new nullable column and shows no write or fetch happens; --plan reports the target schema and the record counts it would touch.


## Notes

**2026-11-11T14:32:38Z**

validated 2026-11-11, left open: not done. Neither archive_backfill_job.py nor lake/daily.py compares the rows to append with the target table's schema before producer-record writes or body fetches (rg for schema_mismatch/target schema finds nothing there); --plan still reads no data.

**2026-11-12T04:33:00Z**

Resolved on `claude/ct-wave-1ab-safety`:
1. Added `inspect_targets`, `verify_target_schemas`, and `writer_field_paths` in `packages/congress_api/src/congress_api/lake/daily.py`. `inspect_targets` reads each target Iceberg table's schema through the engine (`SELECT * FROM "<table>" WHERE FALSE`, zero data scan) and compares all top-level and nested list/struct field paths against the writer's declared and Arrow schemas.
2. Wired `verify_target_schemas` into `daily.produce_daily` (before `_producer_bases`, `_owe_records` producer-record writes, and `_produce` body fetches) and into `archive_backfill_job.execute` (before opening R2 storage or creating `work`).
3. Extended `archive_backfill_job.plan` (`--plan`) to report `writer_schemas` and, whenever a matching catalog runtime is available, engine-inspected `target_schemas` (`columns`, `compatible`, `missing_fields`) and `record_counts` (`total_rows`, `current_rows`, `stale_records`, `would_touch`). Note: per `ba-runbook.md:98-100`, default-mode backfill intentionally has no `archive_disk.py` budget entry (`backfill-record-only` is separate).
4. Verified with failing-first tests `test_target_schema_mismatch_refuses_before_any_producer_record_write_or_body_fetch` (`test_daily_producer_records.py`) and `test_backfill_plan_reports_target_schemas_and_record_counts_and_execute_refuses_before_storage` (`test_archive_maintenance.py`, `65 passed in 3.55s`).
