---
id: ct-clvr
status: closed
deps: []
links: [ct-csyg]
created: 2026-10-20T19:23:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Reuse admitted snapshot planning for occurrence reads

Occurrence capture (`docspec-rs/src/storage/occurrences.rs:133-136,181-185`; `src/storage.rs:644-708`; `src/storage/schema.rs:100-110`) walks all retained snapshot manifests to inventory object closure and then separately replans current-snapshot files through the native planner. Share exact current-file descriptors and tasks within the existing admitted scan context while retaining full object-closure verification at creation and retention boundaries.

## Acceptance Criteria

- Measure manifest opens/decodes and planning latency with fixed current files and growing retained snapshot history (`0 / 8 / 32` snapshots).
- Pass or reuse the already-inspected current-snapshot file descriptors/tasks inside `OccurrenceScan` (`src/storage/occurrences.rs` and `src/storage.rs`) instead of decoding the current snapshot's manifests twice.
- Preserve membership verification, field IDs/defaults, unsupported delete-file refusal (`src/storage.rs:690-694`), old snapshot readers, and bounded memory admission.
- Reuse the maintained Iceberg planner; do not introduce a global cross-request cache or custom Avro manifest parser.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F3. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit validated finding F3 and added exact `src/storage/occurrences.rs:133-136,181-185` and `src/storage.rs:644-708` boundaries.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03a).
- Grades: proposal 88 → 88, work 88 → 88.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
