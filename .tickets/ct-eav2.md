---
id: ct-eav2
status: open
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

