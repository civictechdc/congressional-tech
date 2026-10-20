---
id: ct-3li2
status: closed
deps: []
links: [ct-4nyy, ct-cpio, ct-xl0y, ct-oxg6]
created: 2026-10-20T19:17:09Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, parquet, review]
---
# Sanitize nested export schemas before enabling List and Struct output

Commit `715a8c2` on `docspec-rs` `main` (`298053b`) merged the nested `List`/`Struct` export draft (`src/engine/export.rs:864-930` and `:639-641`), which checks `DataType::List(_)` and `DataType::Struct(_)` only at the root field and clones `field.data_type()` verbatim. Cloned descendant `Field`s retain source `doc`/default/arbitrary metadata in both the Parquet Arrow footer and `ExportField.data_type`, nested unsupported types (e.g., `Map` or `Dictionary` inside a `Struct`) bypass the allowlist, and `footer_group_bytes` counts root columns instead of primitive leaves.

## Acceptance Criteria

- In `docspec-rs/src/engine/export.rs:844-930`, replace the flat root match with a recursive field sanitizer that validates every descendant type against the primitive/container allowlist, preserves only `PARQUET:field_id` metadata on every root and descendant `Field`, and rejects missing/invalid descendant field IDs or `__docspec_` names.
- In `docspec-rs/src/engine/export.rs:639-641`, charge `footer_group_bytes` per primitive leaf column rather than per root field so wide nested structs cannot bypass `limits.max_metadata_bytes`.
- Add unit/integration tests proving: (1) descendant private metadata (`"doc"`, arbitrary keys) is stripped from both the Parquet file footer and `ExportPin.fields`, (2) unsupported nested child types are refused with `unsupported_export_type`, (3) wide nested schemas trigger `metadata_capacity` refusal, and (4) exact nested `List`/`Struct` values and nulls round-trip cleanly.
- Block `ct-oxg6` binary freeze until this fix is committed and verified on `docspec-rs` `main`.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F1. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit confirmed P1 defect in `docspec-rs` `main` (`715a8c2`, `src/engine/export.rs:639-641,864-930`). Upgraded type to `bug` (priority 1) and wired as a hard blocker of `ct-oxg6` and `ct-nc7l`.
