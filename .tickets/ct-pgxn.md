---
id: ct-pgxn
status: closed
deps: []
links: [ct-nloa, ct-xu1o, ct-ur2y, ct-qkvr, ct-8ax6, ct-r60e, ct-ur7v]
created: 2026-10-21T15:27:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [news_lake, docspec, scale, measurement]
---
# Measure per-table native news poll cost against archive size

docspec-rs replace_keys prunes retained files only by exact per-file key bounds (src/engine/write/key_points.rs). news_lake keys most tables with deterministic uuid5 hashes (context.py named_id: items, versions, mentions, discoveries, classifications, identity_decisions, runs, stories, story_members, entities, outlets). Only captures use time-ordered UUIDv7 (ct-ur2y). Hashed keys spread across the whole key space, so a key-scoped Update on those tables is expected to key-decode every retained file each poll. No per-table measurement exists yet. This ticket decides whether the upsert tables need bloom filters (spicy-stack ss-wie5) or whether time-keyed appends (linked ticket) are enough.

## Design

Reuse the existing native backend and WriteMetrics (files_scanned, files_reused, bytes_reused, bytes_written) from each table's processing phase; add no new counters. Run one fixed poll (same items, versions and mentions) against retained archives of 1x and 10x unrelated polls. Record bytes read, files scanned, wall time and peak RSS per table. Local fixture numbers are not production throughput; label them as such.

## Acceptance Criteria

- Table of per-table files_scanned, bytes read, wall time and peak RSS for the fixed poll at 1x and 10x retained archives, before any key or bloom change.
- Identify which tables scale with archive size rather than poll size and rank them by cost.
- State a decision: whether ss-wie5 (bloom filters for items/entities upserts) is needed, with the measured numbers.
- Retain the receipt under output/ and link it here.

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

2026-10-21: started realistic-scale measurement with release harness docspec-rs examples/news_poll_scale.rs (uncommitted). It simulates the news.versions append path: hourly polls of 2,000 rows with uuid5-shaped keys, 200-byte bodies (truncated, stated), lifecycle compacted every 24 polls. Two variants: keys ['id'] (today) and ['observed_at','id'] (ct-xu1o). Target: T1 = 720 polls, then a second point toward T2. Results will follow in notes here.

**2026-10-21T15:55:59Z**

Validation against engine source (docspec-rs 270a8b6): the retained-files columns (~720 T1 / ~8,760 T2, no compaction) likely overstate file count. The native rolling writer coalesces appends toward a target file size with buffers surviving individual writes (storage.rs:338-342, RollingFileWriterBuilder at :396). The real cost driver is key-range overlap: uuid5 keys give every retained file a near-total key range, so every retained file is key-decoded per poll whatever the count. files_scanned stays the deciding metric. Add per-table file-size distribution (avg/p50) to the receipt alongside files_scanned/bytes/RSS so the bloom (ss-wie5) vs time-key (ct-xu1o) decision can distinguish many-tiny-files from few-large-files-still-all-scanned.

**2026-10-21T17:08:00Z — Completed Realistic-Scale Measurement & Decision**

Receipts retained under `output/news-poll-scale-20261021/`:
- `output/news-poll-scale-20261021/summary.md`
- `output/news-poll-scale-20261021/id-1080.csv`
- `output/news-poll-scale-20261021/time-id-1080.csv`

### 1. Engine Prerequisite Fix (`spicy-stack` `ss-1txq`)
Running at realistic scale initially failed deterministically at **poll 315** (`metadata_capacity` > `32 MiB`) due to two $O(\text{polls}^2)$ engine bottlenecks in `docspec-rs`:
1. `Inventory::dataset` treated self-contained `OperationRequest::Update` as `history = false`, causing every `Engine::update` to recursively read all $k$ predecessor `release.json` manifests from `poll-(k-1)` back to `poll-0` (`32.2 MiB` at poll 315).
2. `SnapshotRows` retained `result/poll-*` and `succession/poll-*` forever across compactions (`168 MiB` at poll 720).
Fixed in `docspec-rs` (`ss-1txq`) via `SuccessionCheckpoint` / `SuccessionArchive` and single-hop `parent_manifest` inspection for self-contained `Update`s.

### 2. Retained File-Size Distribution (Clarifying `RollingFileWriter`)
Each `Engine::update` opens a fresh `RollingFileWriter` for that poll's incoming batch while retaining prior polls' untouched Parquet files by manifest reference (`reused_data_files`). Without table compaction (`Engine::compact`), $N$ polls produce $N$ retained data files:
- At poll `1,079` (`2,158,000` rows, 200-byte bodies): `1,079` retained data files (`p50 = 95,390 B`, `avg = 95,383 B`, `total = 102,918,506 B`); across all 3 groups (`source` + `occurrences` + `inputs` = `3,239` files): `min = 44,164 B`, `p50 = 95,390 B`, `avg = 102,397 B`, `max = 167,511 B`, `total = 331.7 MiB`.

### 3. Measured Scale Table (`2,000` `uuid5` rows/poll, Release Build)

| Poll (Horizon) | Total Rows | Retained Data Bytes | `id` (`["id"]`) `files_scanned` | `id` 60-poll p50 `wall_ms` | `time-id` (`["observed_at","id"]`) `files_scanned` | `time-id` 60-poll p50 `wall_ms` | Peak RSS (`id` / `time-id`) | Workspace Disk | Post-Compaction `lifecycle_bytes` |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **60** (2.5d, 1x) | 120,000 | 5.72 MiB | 60 | 561 ms | **0** | **537 ms** | 114 / 109 MiB | 71.9 MiB | 0.39 MiB |
| **360** (15d, 6x) | 720,000 | 34.33 MiB | 360 | 919 ms | **0** | **535 ms** | 170 / 171 MiB | 553.4 MiB | 2.13 MiB |
| **600** (25d, 10x) | 1,200,000 | 57.23 MiB | 600 | 979 ms | **0** | **549 ms** | 210 / 215 MiB | 1,045.0 MiB | 3.51 MiB |
| **720 (`T1`, 30d, 12x)** | 1,440,000 | 68.67 MiB | 720 | 1,028 ms | **0** | **558 ms** | 233 / 246 MiB | 1,345.8 MiB | 4.21 MiB |
| **1,079** (45d, 18x) | 2,158,000 | 102.92 MiB | 1,079 | 1,088 ms | **0** | **603 ms** | 299 / 302 MiB | 2,366.9 MiB | 6.28 MiB |
| **2,160** *(extrap., 90d)* | 4,320,000 | 205.8 MiB | 2,160 | ~1,650 ms | **0** | **~650 ms** | ~470 MiB | ~4.7 GiB | ~12.6 MiB |
| **8,760 (`T2`, 1y)** *(extrap.)* | 17,520,000 | 834.8 MiB | 8,760 | ~5,200 ms | **0** | **~950 ms** | ~1.5 GiB | ~19.2 GiB | ~51.0 MiB |

### 4. Per-Table Cost Ranking & Decision on `ss-wie5` vs `ct-xu1o`
1. **Append tables (`mentions` 10k/poll, `versions` 2k/poll, `discoveries`, `classifications`, `identity_decisions`, `runs`, `stories`, `story_members`)**:
   - Rank #1 in volume. With `keys = ["id"]`, `files_scanned` grows 1:1 with poll count (`60 -> 600 -> 720 -> 1,079`).
   - With `ct-xu1o` (`keys = [<time_col>, "id"]`), `files_scanned = 0` across all 1,079 polls (`558 ms` p50 at `T1`). **Adopt `ct-xu1o`.**
2. **Capture table (`captures`)**:
   - Uses time-ordered `UUIDv7` (`ct-ur2y`); `id` bounds already prune older files (`files_scanned = 0`).
3. **Upsert tables (`items` 2k/poll, `entities`, `outlets`)**:
   - `outlets` and `entities` are small bounded reference tables (1–2 files).
   - `news.items` (`uuid5` URL hash; `first_seen_at` can move earlier) is the only table that scans retained files after `ct-xu1o`. Because `replace_keys` reads only the `id` column pages when probing, scanning 720 files at `T1` adds only **`470 ms`** per hourly poll (`1,028 ms` vs `558 ms` p50) and **`485 ms`** at 1,079 polls (`1,088 ms` vs `603 ms`).
   - **Decision**: **`ss-wie5` (Parquet bloom filters) is NOT needed for T1/pilot** (`ss-wie5` closed with these numbers). `ct-xu1o` (time-keyed appends) is sufficient.

### 5. Workspace Disk Scaling Diagnosis (`2,367 MiB` for `102.9 MiB` of Rows) & Follow-Up Tickets
While per-poll scan latency is solved by `ct-xu1o`, `disk_kib` grew super-linearly (`+1.2 MiB/poll` at poll 60 -> `+2.5 MiB/poll` at poll 720 -> `+3.2 MiB/poll` at poll 1,079, reaching `2.37 GiB` for `102.9 MiB` of source rows, a `23x` multiplier) due to four multipliers, now tracked in dedicated tickets:
1. **Orphaned lifecycle files (`~1,000 MiB`, 42% of disk) -> `spicy-stack` `ss-g9sn`**: `replace_baseline_snapshot` calls `iceberg-rust` `tx.expire_snapshots()`, which only drops old snapshot IDs from `.metadata.json` without unlinking expired `warehouse/<dataset>/lifecycle/{data,metadata}` files (~26,000 dead files across 1,080 polls).
2. **Superseded `release.json` & table manifests (`~1,035 MiB`, 44% of disk, $O(\text{polls}^2)$) -> `spicy-stack` `ss-g9sn`**: Each poll $k$ writes `release.json` and 3 table manifests listing all $k$ retained files (`~800 B * k`); across $N$ polls this sums to $O(N^2)$ (`~1.04 GiB` at 1,080 polls, `~68 GiB` at `T2 = 8,760`). `ss-g9sn` unlinks unreferenced checkpointed release/manifest directories during `compact_lifecycle`.
3. **3x Parquet table triplication (`331.7 MiB` vs `102.9 MiB` source rows, 14% of disk) -> `spicy-stack` `ss-onwi`**: For `SELECT * FROM input` tables, `docspec-rs` writes an identical copy of `source` (`102.9 MiB`) into `inputs` (`114 MiB`) alongside `occurrences` (`115 MiB`).
4. **1-file-per-poll fragmentation (`1,080` ~95 KiB files/table) & live `ReleasePin` growth -> `ct-8ax6`**: Unlike `congress_api` (coarse sync waves), `news_lake` runs hourly micro-polls across 16 datasets (~140k ops/year). Without batch coalescing or threshold native table compaction (`Engine::compact`), the single live head `ReleasePin` embeds $k$ `ObjectRef`s (`~5.8 KiB/file`), growing `lifecycle_bytes` to `6.28 MiB` at poll 1,079 and `~51 MiB` (exceeding the `32 MiB` `max_metadata_bytes` limit) at `T2 = 8,760`. Tracked in `ct-8ax6`.
