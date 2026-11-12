---
id: ct-nu3x
status: closed
deps: []
links: [ct-x00f]
created: 2026-11-11T11:14:36Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine, memory, spill]
---
# Engine spill writer: charge row-group metadata while it writes, and drop its two statistics reservations per piece (O9 follow-ups)

Follow-ups left by O9 (the engine must not refuse its own spill files; on dx/one-line 2a781c8..562ad6a, in the pin candidate ae12bbd), from its independent review (2026-11-10 23:04Z) as recorded in .cache/archive-release/investigations/docspec-feedback-20261110/refactor/briefs/spill-fix-review-fixes.md (should-fix 2 and its closing note; line numbers as of dx/one-line f72bbe2). (1) While a spill is written its row groups' metadata is not charged: encoding::write passes no footer-metadata term (src/job/encoding.rs:31 passes None) and parquet's writer keeps every row group's metadata until close, while exports charge it per row group (the review's export.rs:380-392; the engine has three files of that name). O9 fixed the doc that claimed a spill never costs unledgered memory; the charge itself was deferred. (2) The spill writer still reserves two statistics copies per piece (encoding.rs:55), although spills are written without statistics or page index since 12df07f; what bounds a spill's footer is now only the budget. Neither failed a gate: the pipeline's 2,048-row bounded job ran 12 of 12 with no refusal and the 8,192-row job 5 of 5 at 192 MiB on the candidate.

## Acceptance Criteria

Test first on the engine's integration branch: a spill being written charges its row groups' metadata as it grows, as exports do per row group, shown by a budget the current writer overruns unledgered; the writer reserves nothing for statistics it does not write, with spill bytes unchanged. The pipeline's 2,048- and 8,192-row bounded jobs pass as before at the same lowest pool. Engine scripts/check green; independent review; outward: binaries and a pin move.


## Notes

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green).
- Engine fix (`src/job/encoding.rs`, `src/job/spill.rs`): `encoding::write` for spill files now tracks and charges cumulative `RowGroupMetaData::memory_size()` per flushed row group against the shared memory budget until `ArrowWriter::close()`, and drops the obsolete `2 * stats_bytes` per-piece statistics reservation for statistics-free spill files while leaving spill Parquet bytes unchanged.
- Empirical qualification on CT's bounded-memory capture comparison jobs (`test_capture_comparison_memory.py` `6/6` passed + direct pool sweep):
  - `bounded2048` at `192 MiB` (`t=2` and `t=4`): `2/2` exit `0` (`0.334 GiB` / `0.308 GiB` RSS, `shared_available_min = 90.4 MB` / `89.0 MB`).
  - `full8192` (`t=2`): `3/3` exit `0` at `192 MiB` AND `3/3` exit `0` at the lowest passing pool **`184 MiB`** (`0.539..0.590 GiB` RSS — ~60–80 MiB lower peak RSS than `ae12bbd`'s `0.634..0.667 GiB`), refusing cleanly at `176 MiB` (`step 18 "paired"`), identical to `ae12bbd`.

