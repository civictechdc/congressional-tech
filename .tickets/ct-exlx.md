---
id: ct-exlx
status: open
deps: []
links: [ct-x00f, ct-swyw]
created: 2026-11-10T17:12:33Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, managed-jobs, identity]
---
# Engine: field ids survive a reopened step, so a managed job can reproduce published bytes

Stage 1 of the staged move of the model to managed jobs (owner decision 2026-11-10: option B of .cache/archive-release/investigations/docspec-feedback-20261110/root-cause/MANAGED-JOBS.md, stage 1 may start on the integration branch dx/one-line). The engine's own ticket is def-9ise (docspec-rs/.tickets, open since 2026-10-29). At f803ee6 a Parquet file is read with ParquetReadOptions::default() (src/job/materialized.rs:283, src/job.rs:198), and DataFusion 53.1's default skips Parquet metadata, which drops PARQUET:field_id from top-level fields. A managed job reopens EVERY step from its file (src/engine/managed_job/execution.rs:517), so all 261 materialized steps of the model lose field ids, and 157 fields in 18 published files carry ids today: same rows, different files, a different release id. The on-hold phased model reproduced rows but not bytes for this reason. Care: changing the reader for plain Parquet inputs too (job.rs:198) could itself move today's bytes if an input carries ids; that must be shown on the fixture, not assumed. Links ct-x00f.

## Acceptance Criteria

A test that fails first: a field id written by one step is present in the schema a later step sees after the managed reopen, and in the export's footer. The pipeline's fixture model gives equal output hashes plain against managed for every file (or the remaining differences are listed by cause). Plain jobs on today's inputs give the same bytes before and after (measured on the fixture and on the local measurement job). Independent review; the engine's check green on the integration branch.

