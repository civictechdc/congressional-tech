---
id: ct-mpsp
status: open
deps: []
links: [ct-mi03, ct-a1aa]
created: 2026-10-20T20:37:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, iceberg, partitioning]
---
# Qualify Iceberg Transform::Month partition specs in native table metadata and scans

`docspec-rs/src/storage/tables.rs:18-26` (`fresh_metadata_at`) hardcodes `PartitionSpec::unpartition_spec()`, and both `src/storage/tables.rs:52-60` (`replacement_metadata_at`) and `src/storage.rs:688-695` (`snapshot_files`) explicitly refuse any table where `!default_partition_spec().is_unpartitioned()` with `unsupported_write_layout`. Consequently, `news_lake`'s ADR `I5` (`MonthTransform` on `observed_at` / `recorded_at`; see `docspec-rs/iceberg_optimization_report.md:107-137`) cannot be expressed in native `docspec-rs` tables and currently relies on `Date32` key-scoped copy-on-write replacement.

## Design

Extend `docspec-rs` table creation, replacement metadata validation, snapshot inventory, and batch writing (`src/storage/tables.rs`, `src/storage.rs`, `src/engine/write.rs`) to accept and preserve declared Iceberg partition specs—specifically `Transform::Month` (and `Transform::Day` / `Transform::Identity`) on qualified `Date32` and `Timestamp` source fields—while preserving immutable occurrence identities (`__docspec_file`, `__docspec_row`) and exact field IDs.

## Acceptance Criteria

- `fresh_metadata_at` and `replacement_metadata_at` (`src/storage/tables.rs`) support declared `Transform::Month` partition specs without weakening unencrypted v2/v3 metadata validation.
- `write_batches` and `snapshot_files` (`src/storage.rs`, `src/engine/write.rs`) populate and verify partition values on written `DataFile` entries and preserve unchanged partition files during `Update` and incremental `Refresh`.
- `news_lake` datasets with `I5` `MonthTransform` partitioning round-trip through native `Build`, `Update`, and `Refresh` with exact value and occurrence fidelity.
