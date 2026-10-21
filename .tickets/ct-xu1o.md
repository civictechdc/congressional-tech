---
id: ct-xu1o
status: open
deps: [ct-pgxn]
links: [ct-nloa, ct-pgxn, ct-ur2y, ct-qkvr, ct-8ax6, ct-r60e, ct-ur7v]
created: 2026-10-21T15:27:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [news_lake, docspec, scale]
---
# Key native news appends by an input-derived time column so polls skip old files

Append tables (versions, mentions, discoveries, classifications, identity_decisions, runs, stories, story_members) keep deterministic uuid5 ids by design: replays and duplicate appends must be no-ops (ct-qkvr). Hashed ids give every retained file a near-total key range, so each poll's append check key-decodes the whole table. docspec-rs point pruning (spicy-stack ss-6cz9) already prunes per key column: adding a time column that clusters by poll to the Update keys lets every older file be skipped, with no id change and no engine change.

## Design

In DocSpecLake._commit_append, pass keys=[<time column>, 'id'] instead of ['id']. The contract logical key stays ['id']; only the physical Update key changes. Choose the time column per table from input-derived values that a replay reproduces exactly (for example the capture's fetched_at or the producing run's pinned started_at), never wall-clock time at commit or replay. Tables without such a column keep ['id'] and are listed. Keep the existing conflicting-reuse refusal; it must still see the prior row because a replayed id carries the same time value.

## Acceptance Criteria

- Per table: the chosen column, why a replay reproduces it, or why the table keeps ['id'].
- Replay test: re-running the same poll after a crash or a fresh process is a no-op (no duplicate rows, no new version), and reusing an id with different content is still refused.
- Using the linked measurement fixture: files_scanned for the fixed poll stays flat between 1x and 10x retained archives on converted tables (report numbers).
- Contract and semantics tests pass; stored ids are unchanged.

## Realistic scale (required, added 2026-10-21)

Fixture-sized runs (a few files, tens of rows) prove correctness only; they are not evidence of cost. Qualify at these tiers, stated as assumptions until the pilot measures real volume (docs/packet.md I5: "scale according to measured gaps"):

| Tier | Polls (hourly) | Items/poll | Versions/poll | Mentions/poll | Retained files/table (no compaction) |
|---|---|---|---|---|---|
| T1 pilot month | 720 | 2,000 | 2,000 | 10,000 | ~720 |
| T2 one year | 8,760 | 2,000 | 2,000 | 10,000 | ~8,760 |

- Keys match production shape: uuid5 over the real name templates (context.named_id), not sequential integers.
- Measure at T1 plus at least one larger point toward T2 (for example 2,160 polls = 90 days), and report whether cost per poll is flat or grows with retained size. Extrapolate to T2 from at least two measured points; never from one.
- Record wall time per poll, files_scanned, bytes read, peak RSS, lifecycle metadata bytes and disk used. Use a release build.
- Local constraint: about 55 GiB of free disk. Bodies may be truncated to a fixed realistic length (C5 metadata_only records are valid); state the truncation and that key-probe cost depends on key columns and file count, not body size.

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
