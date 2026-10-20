---
id: ct-wmtx
status: closed
deps: [ct-xl0y]
links: [ct-lcbc, ct-mpsp, ct-a70m]
created: 2026-10-20T18:59:59Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency]
---
# Keep native metadata work bounded as retained history grows

The storage review (`F4`) and the `ct-xl0y` scale study (`docs/experiments/docspec-reuse/native-update-scale.md:132-146`) demonstrated that holding an 8,192-row source pin fixed across 0, 8, and 32 prior empty `Update`s increases single-row correction time from `0.834s` (0 history) to `1.841s` (8 history) and `4.326s` (32 history), with 32 empty `Update`s costing 45.89–65.72s to prepare. Source inspection (`docspec-rs/src/catalog.rs:255-278`, `:370-420`; `src/budget.rs:42`) shows full historical-row replay on cold lifecycle cache misses, whole cached-value map cloning on every commit, and snapshot inventory work across retained history within a 32 MiB metadata allowance that includes superseded records.

## Acceptance Criteria

- Profile cold reopen, warm commit, and alternating datasets with fixed payload and growing history (`0 / 8 / 32 / 128` operations) in `docspec-rs`, reporting wall time, metadata rows/bytes replayed, map clone allocations, and SQLite/Iceberg catalog calls.
- Remove demonstrated duplicate metadata work inside the existing native catalog owner (`src/catalog.rs`), such as avoiding whole-map clones of unchanged keys on commit or introducing a guarded current-state checkpoint while retaining historical/recovery records.
- Preserve exact selected releases, old readers, incomplete operations, and retention roots; do not introduce a second SQL authority or automatic history expiry.
- Adopt a change only with local preservation/recovery tests and measured benefit across growing history; otherwise retain a bounded evidence-based conclusion.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F4. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit incorporated the measured 0/8/32 history growth numbers (`0.834s -> 1.841s -> 4.326s`) from `native-update-scale.md:135-146` and pinpointed `src/catalog.rs:255-278,370-420`.
