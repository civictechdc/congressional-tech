---
id: ct-yndj
status: closed
deps: []
links: [ct-fskn, ct-z4i9, ct-1mq9]
created: 2026-11-10T01:18:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [hosted, archive, maintenance]
---
# Catalog maintenance has never run: readings holds about 1,907 files and 1,294 snapshots

Follow-up to ct-fskn. The weekly hosted maintenance schedule is off because the job was refused on every run (no disk budget names 'maintenance'; refused locally too). So compaction and snapshot expiry have not run: the 2026-11-10 architect review counted readings at 1,907 files and 1,294 snapshots against a 256-file threshold (not re-derived here). To bind the job: a committed hosted budget that names maintenance (measured), fetch-depth: 0 for the ancestry check, and current table names in model/jobs/maintenance.json (the review says it lists two superseded tables and omits three; verify). Run it only outside a release window: it moves catalog heads.

## Acceptance Criteria

One maintenance run finishes green (hosted dispatch or local) with before and after file and snapshot counts per table recorded here, and the schedule is restored in archive-jobs.yml or the reason it stays manual is recorded.


## Notes

**2026-11-10T15:47:02Z**

2026-11-10: prepared, not run (owner decides the run, outside a release window). Being prepared on branch claude/dx-maintenance-prep: the table list checked against the tables the daily and model bind, a disk-budget entry named maintenance, a runbook with the before and after measurements the run should produce and how to stop or undo it midway. Why it matters, measured: readings has 1,907 data files and 1,294 snapshots; one full scan of it takes 23.5 s (profile_reading_duplicates in build c03c43da) and one append took a median 19.6 s (ct-z4i9), and every append anti-joins against every existing file (lake/tables.py append_rows), so the cost of a commit grows with the file count.

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: preparation is on main (W7: fdc767cb maintenance takes its table list from the daily job spec; 9a470972 rebuild and purge need an explicit tables map; merged ab391575), and .github/archive-jobs.json names a 'maintenance' budget. The run itself has not happened: model/jobs/maintenance.json lake_maintenance is still empty and the weekly schedule stays off (archive-jobs.yml:5-6). Waits on the owner's go for the readings move outside a release window.

**2026-11-12T02:42:00Z**

2026-11-12 completed and switched (`archive_r1b.readings` -> `archive_r1b.readings_compact_20261112` on engine `ae12bbd404902bc8fe22a4bdfa357a23fef9e319`, run folder `.cache/archive-release/maintenance/readings-move-20261112T0110Z` from clean checkout at `9d58857c`):

- **S2 local replays (1,416,679 rows, 5 partitions):**
  - `mp2-replay-move` (`sorted`, `compute_threads: 1`, `12 GiB` pool): **12 files** (html 2+3, json 2, sniff 3, xml 2), 187,282,005 bytes, 15.6 s, 8.30 GiB RSS / 7.12 GiB physical.
  - `mp2-replay-nightly-asis` (`asis`, `compute_threads: 2`, `24 GiB` pool): **661 files** (html 64+35, json 140, sniff 211, xml 211), 200,002,318 bytes, 17.1 s, 8.77 GiB RSS / 7.42 GiB physical — proving the earlier ~599-file remote count came from `compute_threads: 2` fan-out rather than R2.
- **Before vs after on R2 (`archive_r1b.readings` -> `archive_r1b.readings_compact_20261112`, 9 partitions):**
  - `total-data-files`: **1,910 -> 35** (stop line 50)
  - `snapshots`: **1,296 -> 1**
  - `metadata_bytes`: **907,420 -> 3,941**
  - `total-files-size`: **250,037,779 -> 229,676,793**
  - `total-records`: **1,654,201 -> 1,654,201** (identical row counts across all 9 `(parser, parser_version)` partitions)
  - Read probes: `partitions` **17.40 s -> 1.65 s**, `full_scan` **17.74 s -> 3.46 s** (`<= 6 s` prediction met), `append_probe` **17.59 s -> 4.02 s**.
- **Verification (`V1`–`V4`):**
  - `V1`: `archive_import_job` EXCEPT ALL against sorted export (`readings.parquet`, sha256 `59bdfa95…`, 241,726,756 bytes) + `verify_generations(exact=True)` typed EXCEPT ALL both ways and primary-key checks (`rc=0`).
  - `V3`: full model build from `release-20261112-pin/candidate-at-gate` (`21fc049940bb`) at `old` (`443 s`, `10.62 GiB` RSS) vs `new` (`368 s`, `9.99 GiB` RSS, **75 s faster**) produced **32/32 byte-for-byte SHA-256 identical files** in `archive-release/` (including `manifest.json` release id `21fc049940bbe4ef75ab774b3cc74a5e746fb9f023afb9a896059d595f5fa381`).
  - `V4`: `mp2_repoint.py` verified gate-5 provenance offline (`producers/readings-compact-20261112.json`, sha256 `df87da0a…`) and repointed `publish-daily.json`, `backfill.json`, `publish-model.json`, and `publish.json`.
- **Superseded generation retained for later Step 13 purge (once no kept release pins its UUID):**
  - Table `archive_r1b.readings`, `table_uuid: 01a1a35e-550f-79f2-81a2-b7412fd72bc6`, `snapshot: 4472402246940841528`, `metadata_location: s3://congressional-tech-raw/__r2_data_catalog/ct-archive-v2/archive_r1b/readings/metadata/01296-01a1c6dd-d252-7a93-9e5d-fa506119d884.gz.metadata.json`.
  - New active table `archive_r1b.readings_compact_20261112`, `table_uuid: 01a1cd80-8888-7632-9a00-2f51f88af451`, `snapshot: 5394364687916217001`, `metadata_location: s3://congressional-tech-raw/__r2_data_catalog/ct-archive-v2/archive_r1b/readings_compact_20261112/metadata/00001-01a1cd81-4240-70f3-be49-119697abc612.gz.metadata.json`.
- **Why the weekly schedule in `.github/workflows/archive-jobs.yml` stays manual:**
  - `model/jobs/maintenance.json` intentionally keeps `lake_maintenance` empty because `lake/maintenance.py` rebuild creates unpartitioned 8,192-row batches without a gate-5 producer record (refused by `9a470972`), hosted runners have no measured `maintenance` disk-budget source yet (`archive-jobs.yml` maintenance checkout also lacks `fetch-depth: 0`), and at ~+3 files/night regrowth `readings_compact_20261112` has ~77 nights before reaching the 256-file threshold (with engine Stage 1c snapshot baseline compaction `ct-twfj` also landing).
