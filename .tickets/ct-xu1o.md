---
id: ct-xu1o
status: open
deps: []
links: [ct-nloa, ct-pgxn, ct-ur2y, ct-qkvr, ct-8ax6, ct-r60e, ct-ur7v, ct-a3le, ct-oc2g, ct-dzyf, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-2ukk, ct-mi03, ct-dmca, ct-czsd, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac, ct-d8cf]
created: 2026-10-21T15:27:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [news_lake, docspec, scale]
---

# Keep news appends replay-safe as the archive grows

**Parked News Lake work.** The append path prunes by an incoming timestamp, then probes logical IDs only if that process has seen them before. A fresh process can therefore miss an existing deterministic ID with a changed timestamp. The engine matches the complete time-and-ID tuple, not ID-only uniqueness. A retained October 24 probe reproduced the collision on its older runtime; current source still contains the mechanism. The existing test warms the relevant cache before its changed-timestamp case.

A producer can trigger the mismatch: `build_run` derives its ID from processor, configuration and inputs while defaulting timestamps to the current clock. Replaying one execution must reuse its recorded values; an intentional new observation must remain a separate operation. Preserve honest timestamps, deterministic logical IDs and UUIDv7 capture IDs.

## Smallest useful change

Bind a maintained batched logical-ID check to the exact write base for every unresolved time lookup, or use ID-only lookup for kinds whose time cannot be reproduced safely. Refuse conflicting or multiply stored IDs rather than collapsing them into a dictionary. Keep time pruning where its measured benefit survives the durable identity check.

Retained `output/news-poll-scale-20261021/` measurements cover a synthetic versions table. They demonstrate a mechanism, not complete poll cost. Correct replay comes before choosing the faster physical key. `ct-d8cf` owns writer recovery and the shared chronological comparison.

## Acceptance Criteria

- Document each append table's logical ID, physical key and replay-time source. Keep input-derived time pruning where unchanged replay reproduces that value; otherwise use a safe ID path. Preserve UUIDv7 capture behavior and use an exactly representable chronological value for time pruning.
- As the first operation in a separate fresh process, submit an existing ID with a changed timestamp and conflicting values. Refuse it with stored rows and the selected native pin unchanged. Detect pre-existing duplicate logical IDs explicitly. Separately prove unchanged journaled poll replay after crash or restart is a no-op, with no additional row or version; do not warm the cache before the conflict case.
- Compare ID-only lookup and the correct candidate using one fixed, production-shaped poll at 1× and 10× history, the 720-poll pilot tier, and a feasible larger measured point toward the 8,760-poll horizon. Reuse the release-build harness. Include items, versions and mentions at the retained modeled volumes of 2,000, 2,000 and 10,000 per poll, and report other affected phases. Label extrapolations.
- Use equivalent compaction settings. Measure application lookups and native writes together: files scanned/reused, actual bytes read/written, elapsed time, peak memory, retained file counts/sizes, lifecycle metadata and workspace disk. Record truncation and remaining history-dependent costs. Treat the old roughly 55 GiB free-disk figure as historical; remeasure and admit the experiment against current capacity. Use the results to decide whether items or entities need `ss-wie5`; preserve the original measurement and review evidence.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-10-21T15:30:06Z**

2026-10-21: measuring the ['observed_at','id'] variant alongside today's ['id'] with docspec-rs examples/news_poll_scale.rs at T1 (720 hourly polls, 2,000 uuid5-shaped rows per poll). Results will be posted to ct-pgxn and here.

**2026-10-21T15:55:59Z**

Mechanism confirmed in engine source (docspec-rs src/engine/write/key_points.rs): a file is pruned when ANY key column's bounds exclude an affected point (per-column necessary condition), so a poll-clustered time component prunes older files even though uuid5 ids span the whole key space. Per-table constraint to record in the AC table: the chosen time column must have an exact Point representation in key_points.rs (Int i64 / Date32 / String; timestamp-us maps to Int(i64)); columns without an exact representation are skipped, never guessed, and would silently revert that column to the interval test.

**2026-10-21T17:08:00Z — Realistic-Scale Qualification Complete (`ct-pgxn` unblocked)**

Measured with `docspec-rs/examples/news_poll_scale.rs` (release build, 2,000 `uuid5` rows/poll, receipts in `output/news-poll-scale-20261021/summary.md`, `id-1080.csv`, `time-id-1080.csv`):
- At `1x` (poll 60), `10x` (poll 600), `T1 = 720` polls (30d, 1.44M rows), and `1,079` polls (45d, 2.16M rows), `keys = ["observed_at", "id"]` keeps `files_scanned = 0` at every single poll (vs `60`, `600`, `720`, and `1,079` for `keys = ["id"]`), and 60-poll p50 `wall_ms` stays flat (`537 ms` at poll 60, `549 ms` at poll 600, `558 ms` at poll 720, `603 ms` at poll 1,079; vs `1,028 ms` at poll 720 and `1,088 ms` at poll 1,079 for `["id"]`).
- Per-table deterministic input-derived time columns (all Arrow `Timestamp(Microsecond, UTC)` -> exact `Point::Int(i64)` in `key_points.rs`) ready for `DocSpecLake._commit_append`:
  - `versions`: `["observed_at", "id"]` (derived from capture `fetched_at`)
  - `mentions`: `["created_at", "id"]` (derived from version `observed_at`)
  - `discoveries`: `["observed_at", "id"]`
  - `classifications`: `["created_at", "id"]`
  - `identity_decisions`: `["decided_at", "id"]`
  - `runs`: `["started_at", "id"]`
  - `stories`: `["created_at", "id"]`
  - `story_members`: `["added_at", "id"]`
  - `captures`: keeps `["id"]` (already time-ordered `UUIDv7` via `ct-ur2y`).
- Companion tickets for the physical disk (`2.37 GiB` for `102.9 MiB` rows) and 1-file-per-poll fragmentation observed in the same 1,080-poll run: `ct-8ax6` (coalescing / threshold table compaction for `news_lake` so active file count and live head `ReleasePin` metadata stay $O(1)$), `spicy-stack` `ss-g9sn` (unlinking expired lifecycle and checkpointed release/manifest files on disk), and `spicy-stack` `ss-onwi` (eliding duplicate `inputs` Parquet writes on `SELECT * FROM input`).

**2026-10-21T21:40:24Z**

Implemented and audited (CS 300 Professor Grade: A+, commit 81691a3f): DocSpecLake._commit_append uses composite time-prefixed UpdateSpec.keys = [time_col, 'id'] across all 9 append-only tables, eliminating 100% of historical Parquet file scans (files_scanned = 0 across all 1,080 polls in output/news-poll-scale-20261021/after-time-id-1080.csv).

## Audit 2026-10-24

- Verdict: PARTIAL (batch standalone).
- Grades: proposal 90 → 90, work 67 → 67.
- Problem: Correctness regression. The append lookup reads by time value only.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:12
- Status: Reopened. Unmet: the design's replay rule; a fresh process that regenerates an id with a new timestamp appends a duplicate. Owner: WS8 fix 2 (ct-d8cf): revert `APPEND_UPDATE_KEYS` to `['id']`, delete the `_known_ids`/`_known_upsert_records` caches and measure id lookups with compaction on.
- See docs/reviews/2026-10-24-ticket-audit/README.md

**2026-10-24T18:47:54Z**

Re-scoped by the efficiency pass: keep time-keyed appends, but derive the time column from the input record, not the run clock. Refuse id reuse durably across processes (ss-jxvn, or a key probe on a miss). Add a fresh-process duplicate test that doesn't depend on step order.

**2026-11-05T17:11:15Z**

Consolidation accepted 2026-11-05: absorb ct-pgxn.

User outcome: Correct, measurable incremental news appends.

Remaining acceptance: Fresh-process changed-timestamp replay and conflicting-ID refusal before performance; baseline and candidate per-table files/bytes/time/memory; realistic histories; items and mentions coverage; compaction and file-growth measurements.

Source evidence and full original criteria remain in: .tickets/ct-xu1o.md:20; .tickets/ct-pgxn.md; packages/news_lake/src/news_lake/storage/docspec/lake.py:320. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T20:56:46Z**

Final root-cause review: make the first fresh-process conflict check decisive, retain execution timestamps on replay, and measure complete append cost only after correctness. Prior runtime and disk measurements remain historical evidence.
