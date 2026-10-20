---
id: ct-cpio
status: closed
deps: [ct-xl0y]
links: [ct-xl0y, ct-oxg6, ct-3li2]
created: 2026-10-20T19:23:00Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Separate native Parquet layout from reader batch sizing

Native row-group rows and target file bytes originally reused transient reader limits (`batch_rows` default 4,096; `max_batch_bytes` default 64 MiB). However, commit `715a8c2` on `docspec-rs` `main` (`298053b`) changed `src/engine/write.rs:429-456` to force `max_row_group_row_count(1_000_000)` and `max_row_group_bytes(Some(budget.limits.max_batch_bytes.max(128 * 1024 * 1024)))`, and hardcoded `news_lake` column names (`["resolution", "aboutness", "processor", "provider"]`) into `src/engine/write.rs:451-455` and `src/engine/export.rs:601-604`.

Using `.max(128 MiB)` overrides smaller caller-configured `max_batch_bytes` budgets (such as 1 MiB / 4 MiB / 16 MiB bounds in tests and adoption leaves), violating bounded writer buffering, while the hardcoded column dictionary loop is both domain-coupled and redundant because `WriterProperties::default()` in `parquet 58.4.0` already enables dictionary encoding globally.

## Acceptance Criteria

- In `docspec-rs/src/engine/write.rs:429-456` and `docspec-rs/src/engine/export.rs:588-605`, remove the hardcoded `news_lake` column dictionary loop (relying on default `dictionary_enabled(true)`).
- Restore strict compliance with `budget.limits` so a caller's configured `max_batch_bytes` and `batch_rows` are never exceeded by an unconditional `.max(128 MiB)` or `1_000_000`-row floor.
- If separating row-group byte targets from reader `batch_rows`, expose or bound the target within `Limits` (`max_batch_bytes` ceiling), hold batch memory fixed, and measure group/file distribution, footer bytes, compression, read/update cost, peak memory, and retained bytes before adopting any default change.
- Block `ct-oxg6` binary freeze until caller `Limits` enforcement is restored on `docspec-rs` `main`.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F5. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit flagged P1 regression risk in `docspec-rs` `main` (`715a8c2`, `src/engine/write.rs:437-455` and `src/engine/export.rs:593-604`): `.max(128 * 1024 * 1024)` ignores tighter `Limits.max_batch_bytes` and hardcodes `news_lake` column names in a domain-neutral engine. Upgraded to priority 1 bug blocking `ct-oxg6` and `ct-nc7l`.

**2026-10-20T22:19:32Z**

Fresh9661026 source confirms production writer coupling remains: src/storage.rs:369 and src/engine/export.rs:601 repeat dictionary=true for resolution/aboutness/processor/provider after global dictionary=true. Remove these redundant news-column names from the generic engine. Test-only news-shaped profiling fixtures may remain; no application business policy belongs in writers.

**2026-10-20T22:24:50Z**

Final static review through native 22a804e: hardcoded news-column dictionary loops have been removed from both production writers. Caller-byte row-group limits also landed. ct-oxg6 still requires exact chosen-runtime safety evidence; this note does not close the upstream ticket or claim runtime qualification.
