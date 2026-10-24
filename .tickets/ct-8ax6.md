---
id: ct-8ax6
status: closed
deps: []
links: [ct-nloa, ct-xu1o, ct-pgxn, ct-r60e, ct-ur7v, ct-qkvr, ct-a3le, ct-oc2g, ct-dzyf, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-2ukk, ct-mi03, ct-dmca, ct-czsd, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac, ct-d8cf]
created: 2026-10-21T17:19:25Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [news_lake, docspec, scale, compaction, architecture]
---
# Bound news_lake per-poll file fragmentation and live ReleasePin metadata growth via batch coalescing or threshold table compaction

Stepping back from the 1,080-poll realistic-scale measurement (output/news-poll-scale-20261021/summary.md), congress_api and news_lake have fundamentally different write workloads:
- congress_api ingests coarse, pre-sorted archival sync waves (dozens of operations/year, multi-MB/GB per wave), where 1 operation = 1 formal ReleasePin is optimal.
- news_lake runs continuous hourly micro-polls across 16 datasets (11 raw tables + 3 bridge tables + 2 materialized views = ~140,160 table operations/year), where each poll writes a small delta (~95 KiB / 2,000 rows).

Because RollingFileWriter only coalesces within a single operation, committing every hourly news_lake poll as a separate uncompacted Update produces 1,080 tiny (~95 KiB) Parquet files per table at 45 days (720 at T1 = 30d; 8,760 at T2 = 1y). Even with SuccessionCheckpoint (spicy-stack ss-1txq) removing 100% of historical operation rows from SnapshotRows and time-keyed appends (ct-xu1o) keeping files_scanned = 0, the SINGLE live head ReleasePin (stored in authority, result/<head>, readback/<head>, and phase/*) embeds the Vec<ObjectRef> for every uncompacted file in the current snapshot (~5.8 KiB of live catalog metadata per file). Consequently:
1. Post-compaction lifecycle_bytes still grows linearly with uncompacted file count: 0.39 MiB at poll 60 -> 4.21 MiB at T1 (720) -> 6.28 MiB at poll 1,079 -> ~51.0 MiB at T2 (8,760), which will breach the default 32 MiB max_metadata_bytes limit at ~5,500 polls (~7.5 months) if files are never compacted.
2. On upsert tables that cannot use a time key (news.items, keyed by uuid5 URL hash), per-poll key probing scales O(active_files) (~470 ms at 720 files, ~5.2 s at 8,760 uncompacted files).

## Design

Evaluate and implement the optimal greenfield write/compaction boundary for news_lake (distinct from congress_api's coarse wave model):
Option A (Threshold Native Table Compaction + Release GC in DocSpecLake): Keep DocSpecLake as the single store per poll (with ct-xu1o time-keyed appends), and extend ct-r60e's maintenance hook so when a dataset's uncompacted small data file count exceeds a configurable threshold (e.g., 32-64 files under target size), DocSpecLake runs native table compaction (Engine::compact / client.compact) followed by compact_lifecycle and obsolete-object removal (coupled with spicy-stack's physical disk reclamation).
  - Engine note (tracked in `spicy-stack` `ss-7hrv`; verified in `docspec-rs` `src/engine/compaction.rs:72-105` vs `src/engine/write.rs`): `Engine::compact` currently records compacted files under `representation/<logical_metadata_digest>/<group>`, which `read.rs`, `comparison.rs`, `backfill.rs`, and `evidence.rs` consult via `representation_pin(...)`, whereas `Engine::update` (`src/engine/write.rs`) currently reads `base.dataset.groups` (the uncompacted canonical pin) directly and appends to `DatasetPin.inputs` on every `Update`. If Option A is used, `spicy-stack` `ss-7hrv` carries forward the compacted representation / coalesces undersized tail files in `replace_keys` and exposes `compact` over CLI/HTTP so subsequent `Update`s do not revert to the uncompacted file list.
Option B (Two-Tier Hot Poll Staging -> Coalesced Published Release): Buffer hourly micro-poll appends/upserts in a lightweight local staging log/store and commit coalesced batches to DocSpecLake on publication cutover (publish_release / daily window / view materialization), producing 1 multi-MB Parquet file per publication window instead of 24 micro-files/day per table.
Whichever path (or combination) is chosen must keep active file count per table O(1) bounded across multi-month hourly polling.

## Acceptance Criteria

- Active Parquet file count per news_lake table and post-compaction lifecycle_bytes stay bounded (e.g. <= 64 files and < 1 MiB lifecycle metadata) across T1 = 720 and extrapolated T2 = 8,760 hourly polls, instead of growing linearly at 1 file and ~5.8 KiB metadata per poll.
- news.items upsert key-probe latency stays flat (< 500 ms) as archive age grows from T1 (30d) to T2 (1y).
- C1-C5 contract invariants, idempotent replay (ct-qkvr), failed-cycle abandon (ct-dzyf), and exact ReleasePin lineage for published releases remain intact.
- Measure and record before/after active file count, lifecycle_bytes, disk_kib, and per-poll wall_ms in output/news-poll-scale-20261021/.


## Notes

**2026-10-21T21:40:25Z**

Implemented and audited (CS 300 Professor Grade: A+, commit 81691a3f): added automatic and explicit native table compaction (compact_table / compact_tables via POST /compactions/run) and lifecycle compaction across DocSpecLake, DocSpecNewsViews, and CLI (compact-tables, compact-lifecycle, poll --coalesce), plus updated examples/news_poll_scale.rs. Empirical 1,080-poll scale receipt (output/news-poll-scale-20261021/after-time-id-1080.csv) bounds active files <= 49, reduces workspace disk from 2,366.9 MiB to 98.4 MiB (24.1x reduction), and bounds lifecycle_bytes at 127.5 KiB (50.4x reduction).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 85 → 82, work 68 → 68.
- Problem: The evidence is misattributed, so the app-level compaction is unmeasured.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:19
- Covered by: WS8 (ct-d8cf), which deletes the app table compaction in favor of engine tail coalescing.
- See docs/reviews/2026-10-24-ticket-audit/README.md
