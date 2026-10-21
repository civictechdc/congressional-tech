---
id: ct-nmjc
status: closed
deps: []
links: [ct-tuez, ct-mi03]
created: 2026-10-21T14:41:26Z
type: task
priority: 1
assignee: mikewolfd
tags: [docspec_client, parquet, scale]
---
# Bound producer Parquet row_group_size in docspec_client to prevent contiguous StringArray buffer oversized_batch refusals at scale

When NativeDatasets.run_table and NativeDatasets.update_table (packages/docspec_client/src/docspec_client/docspec.py:390-515) write an in-memory PyArrow Table to source.parquet / replacements.parquet / deletions.parquet, pq.write_table is called with PyArrow's default row_group_size (1,048,576 rows). On our 262,144-row production scale test (filenames.parquet scalar columns), PyArrow wrote all 262,144 rows into a single row group whose decoded StringArray buffer occupied 5,567,060 bytes. Even when docspec-rs batch_rows was lowered to 1024, Arrow's zero-copy slice batch.get_array_memory_size() inside docspec-rs (src/storage.rs:411) counted the entire 5.57 MB contiguous page/row-group buffer and refused admission with oversized_batch when max_batch_bytes was 4 MiB.

## Design

In packages/docspec_client/src/docspec_client/docspec.py, configure producer Parquet writes in run_table, update_table, and update_evidence_table to pass a bounded row_group_size (e.g., matching configured limits batch_rows or min(batch_rows, 2048), default 2048) and compression='zstd'. Also evaluate decoupling reader batch buffer admission from output target_file_bytes in docspec-rs (src/storage.rs:283,363) so small reader batches do not force tiny output files.

## Acceptance Criteria

- NativeDatasets.run_table and update_table write producer Parquet files with bounded row_group_size (<= configured batch_rows / 2048) and compression='zstd'.
- Submitting a 262,144-row in-memory table with 64-300 byte string columns under max_batch_bytes=4 MiB and batch_rows=1024 succeeds without requiring the caller to manually pre-chunk row groups.
- Add a unit/scale regression test in tests/test_docspec_runtime.py verifying bounded row_group_size in producer Parquet files.

