---
id: ct-rax4
status: closed
deps: []
links: [ct-64t4]
created: 2026-11-11T03:14:21Z
type: task
priority: 2
assignee: mikewolfd
tags: [nightly, engine, limits]
---
# Route the backfill, import and maintenance runtime choice through choose_runtime and runtime_record

Follow-up from W5 (ct-64t4). Three jobs choose their engine runtime by a second rule of their own, copied three times: the spec's engine_config, else DOCSPEC_RUNTIME_CONFIG, else DOCSPEC_JOB_CONFIG (archive_backfill_job.py execute near :344, archive_import_job.py near :140, archive_maintenance.py near :473, where the last step needs an engine). None records what it ran under. The nightly runs the backfill unattended when the daily reports backfill_required (scripts/nightly_publish.py near :453), so a backfill's runtime and limits are as invisible as the model's were before W5. Route all three through docspec_client.client.choose_runtime (one owner of the choice; it has to learn the absent-field case and the DOCSPEC_JOB_CONFIG step) and record with runtime_record where each run already writes its evidence. Changing the order or the variables changes what the nightly's backfill does unattended: an owner decision, as the publisher's fallback is.

## Acceptance Criteria

One owner chooses the runtime for all five callers; each run's existing evidence names the runtime file, binary and limits it ran under and how they were chosen; tests with constructed runtimes and a decoy show each caller records the same fields; the choice order is unchanged unless the owner decides otherwise.


## Notes

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: not done. On origin/main 17a283bc only the model job and the publisher use choose_runtime/runtime_record (archive_model_job.py:423-428, archive_publish_job.py:475-485); the backfill (archive_backfill_job.py:345), import (archive_import_job.py:140) and maintenance (archive_maintenance.py:493) still pick engine_config or DOCSPEC_RUNTIME_CONFIG by their own copies and record nothing. Changing the order stays an owner decision.

**2026-11-12T04:53:00Z**

Closed on `claude/ct-wave-1ab-safety`. Extended `docspec_client.client.choose_runtime` (`named=None, *, job_fallback=False`) to handle absent `engine_config` fields and the `DOCSPEC_JOB_CONFIG` third step while preserving the exact existing precedence for all five callers:
- `archive_model_job` and `archive_publish_job` (`job_fallback=False`): explicit `engine_config` when present (or `DOCSPEC_RUNTIME_CONFIG` when a named file is missing), else `DOCSPEC_RUNTIME_CONFIG` when `engine_config` is omitted; never falls back to `DOCSPEC_JOB_CONFIG`.
- `archive_backfill_job` (`execute` + `plan`), `archive_import_job`, and `archive_maintenance` (`job_fallback=True` when `need_engine`): explicit `engine_config`, else `DOCSPEC_RUNTIME_CONFIG`, else `DOCSPEC_JOB_CONFIG`.
- All five callers emit the `[docspec-runtime]` stderr line before work and record `engine_config` and `engine_runtime` (`runtime_record` with runtime, binary, and limits paths/sha256s/values plus choice rationale) in their durable JSON reports (`backfill-report.json`, `import-report.json`, `maintenance-report.json`, model result line, and `model-intent.json` / `completed-model.json`).
- Verified with constructed runtimes and decoys across all callers in `packages/viewer_publication/tests/test_runtime_record.py` (374 passed across 10 test files).
