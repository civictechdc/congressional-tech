---
id: ct-exlx
status: closed
deps: []
links: [ct-x00f, ct-swyw, ct-tx7u]
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


## Notes

**2026-11-11T11:14:25Z**

2026-11-11: for the one-line pin the owner accepted field ids on lake-copied columns ('Accept them', relayed by the coordinator at 09:22Z): on the candidate ae12bbd, columns the model copies from lake tables carry their source column's Iceberg field id. Read from the lake-backed fixture run: 11 file-and-column pairs in 6 files, 9 distinct columns, for example detail.parquet and document_rows.parquet saved_bytes (21) and in_archive_since (36), url_state.parquet requested_url (8) (PIN-MOVE-QUALIFICATION.md section 2, from refactor/one-line/ol_bytes_w12lake_pinned_vs_tip7aa59e3.json). The byte test accepts a field id only on a column copied from a lake table and equal to that column's id. This ticket still sets field ids deliberately; the pinned behaviour is its starting point (stage 1a), and the release note says a later engine change assigns them.

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green; `darwin-arm64` SHA-256 `86255b5f851d53992e6ae81465ed575bee266da4557389c69aedc3abc52715cc`, `linux-amd64` SHA-256 `3e7e1b7412eb214e69b9b8007b8b021aa1ec84a5a10279723f900e9b12e9b92c` in R2 `congressional-tech-runtime`).
- Engine fix (`src/engine/managed_job/execution.rs`, `src/job/materialized.rs`): managed step reopen sets `.with_skip_metadata(false)` on `ParquetReadOptions` so `PARQUET:field_id` survives across reopened steps (`def-9ise` / Stage 1b), while plain Parquet input reads preserve today's exact `ParquetReadOptions::default()` behavior so plain jobs do not shift bytes.
- Regression tests in `docspec-rs` (`tests/managed_jobs.rs`): field IDs written by step 1 survive managed reopen into step 2's schema and final exported Parquet footer, and plain vs managed job exports produce equal output hashes.
- Full local CT production model build (`release-20261112-pin2/candidate-build`, `release_id = 06cd8374d1609d0e6c2d34b48824c89b65b4519de0317212f38af71768aa755e` vs `ae12bbd` control `ede659a056c04ce0c4f51c70b6848b4eaf1db1a2a2fa8aee04076973e2a1a450`): all 46 `.parquet` files (28 published in `archive-release/` + 18 in `archive-model/evidence/`) plus `schema.json` and `capture_scope.json` are 100% SHA-256 byte-for-byte identical, and 5-hop horizontal raw-data trace verified exact `PARQUET:field_id` preservation on `detail.saved_bytes` (`21`), `detail.in_archive_since` (`36`), `document_rows.saved_bytes` (`21`), `document_rows.in_archive_since` (`36`), and `url_state.requested_url` (`8`) through Explorer Playwright UI and FastMCP `StdioTransport`.
