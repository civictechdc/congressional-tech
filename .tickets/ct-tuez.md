---
id: ct-tuez
status: closed
deps: []
links: [ct-mi03, ct-ur2y, ct-nmjc]
created: 2026-10-21T14:40:30Z
type: task
priority: 1
assignee: mikewolfd
tags: [docspec, parquet, iceberg, scale]
---
# Raise Parquet statistics truncation ceiling to 128 bytes so 64-byte SHA-256 and 74-byte body_key columns prune files

Empirical scale probing across 8,132,141 production rows (output/incremental-updates-20261019/adoption-inputs/) on docspec-rs 96e3826 showed that 100.00% of source_id (1,683,430 rows) and document_id (1,241,157 rows) are 64-byte SHA-256 hex strings, 98.52% of filenames.body_key (1,658,450 rows) are 74 bytes ('bodies/<64-hex>.gz'), and 73.35% of captures.sha256/body_key (2,867,269 rows) are 64-74 bytes. Because docspec-rs sets .set_statistics_truncate_length(Some(64)) in src/storage.rs:383, untruncated_bound (src/engine/write.rs:907), KeyTargets::file_may_contain (src/engine/read.rs:397-404), KeyPoints::may_contain (src/engine/write/key_points.rs:178), and untruncated_file_bounds / scalar_to_primitive_literal (src/query.rs:499,520) treat every string bound with s.len() >= 64 as potentially truncated (None). On a 262,144-row (28-file) sorted production dataset, 64-byte source_id keys forced Update to probe all 25 source files (files_scanned=26) and read_keys to take 0.3106s, whereas 32-byte keys pruned 24/25 files (files_scanned=2) and took 0.0217s (14.3x faster).

## Design

Define a single shared constant STATISTICS_TRUNCATE_BYTES = 128 in docspec-rs (src/storage.rs, src/engine/write.rs, src/engine/read.rs, src/query.rs), configure WriterProperties::set_statistics_truncate_length(Some(128)), and require s.len() < 128 / b.len() < 128 in untruncated_bound, untruncated_file_bounds, and scalar_to_primitive_literal. Existing 64-byte truncated bounds in historical files remain >= 64 only if written under the old setting; verify whether existing uncompacted test fixtures need a migration note or only newly written/compacted files gain 64-127 byte pruning. Note that RoutingPages and CatalogMemberships must still be retained for congress_api because 93.91% of state.parquet _state_key URLs (up to 976 bytes) and 70.35% of source_url values exceed 64-128 bytes and require prefix-routed 8,192-row leaves plus guarded CAS selection.

## Acceptance Criteria

- docspec-rs sets statistics_truncate_length(Some(128)) and uses < 128 in untruncated_bound, untruncated_file_bounds, and scalar_to_primitive_literal.
- On a multi-file dataset keyed by 64-byte hex SHA-256 strings or 74-byte body_key strings with disjoint file key ranges, both read_keys and replace_keys (Update) prune non-overlapping files (files_scanned == 2 for a single-key update across N files).
- Strings of length >= 128 bytes (such as long URLs) continue to fall back conservatively without false pruning.

## Notes

**2026-10-21T16:40:00Z**

Implemented in `docspec-rs` `eba36fa` (`STATISTICS_TRUNCATE_BYTES = 128` in `src/storage.rs:30`, `src/engine/export.rs`, `src/engine/write.rs:907`, `src/query.rs:500,523`). Verified in `src/query/pruning_tests.rs`, `tests/update_pruning.rs::sha256_string_keys_prune_disjoint_files_on_update`, and on 262,144 sorted production rows (`filenames.parquet`): 64-byte SHA-256 `source_id` keys now prune disjoint files identically to 32-byte keys (`files_reused: 0 -> 6`, `files_scanned: 2`, `single_key_update_sec: 5.11s -> 1.63s` [3.14x faster], `read_keys: 0.219s -> 0.077s` [2.85x faster]).


## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch standalone).
- Grades: proposal 94 → 94, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
