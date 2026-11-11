---
id: dle-rax4
status: open
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

