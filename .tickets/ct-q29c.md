---
id: ct-q29c
status: closed
deps: []
links: [ct-r6xw]
created: 2026-10-22T18:41:23Z
type: bug
priority: 0
assignee: mikewolfd
parent: ct-4t6s
tags: [parquet, r2, weekly-tables, congress-api, bug, normalization]
---
# Fix 5 broken weekly_tables.py row builders (99.94% youtube_videos row loss & 100% NULL order_by columns), normalize all 10 weekly schemas, and offload raw bodies to R2

Testing all 10 row builders in packages/congress_api/src/congress_api/retention/weekly_tables.py and sync_weekly_tables.py against real production data in /Users/mikewolfd/Work/pipeline-data uncovered critical data-corruption bugs in 5 of the 10 tables plus massive payload_json duplication:
1. youtube_videos (weekly_tables.py:421-429, sync_weekly_tables.py:74-76): youtube_video_to_row looks up record.get('video_id') and record.get('published_at'), whereas decode_cache(tables).videos() yields camelCase 'videoId' and 'publishedAt'. On real data, 100% of the 67,351 videos get video_id='' and published_at=None (the merge order_by column!), and because WEEKLY_TABLE_KEYS['youtube_videos'] = ('system_code', 'video_id'), all ~1,500 videos per channel collapse into a SINGLE row with video_id='' (67,351 rows -> 43 rows, 99.94% data loss!). Furthermore, payload_json (266.78 MB) is 82.8% (221.02 MB) upstream API envelopes repeating description 4x (71.45 MB vs 17.86 MB unique), title 4x, and thumbnails 2x.
2. congress_committees (weekly_tables.py:354-363, retention/committees.py:32): committee_to_row reads top-level record.get('systemCode'), 'chamber', and 'updateDate', which are 100% NULL because CommitteeSnapshot nests them under record['committee']. Worse, _url is the Congress listing URL (only 14 unique values across 3,424 rows!), retention/committees.py:32 calls write_jsonl without dataset='congress_committees', sync_weekly_tables.py omits congress_committees, and Congress-independent record['detail'] is duplicated 9.50x across Congresses (6.28 MB vs 660 KB unique = 67.8% of table).
3. gpo_observations (weekly_tables.py:400-418): gpo_observation_to_row looks up record.get('observations'), which does not exist in GpoEvidenceRecord ({'package_id', 'parser_version', 'listing', 'mods', 'transcripts'}). Both retrieved_at (the merge order_by column!) and acquisition are 100% NULL across all 644 rows.
4. house_events (weekly_tables.py:366-373): house_event_to_row only checks record.get('imported_at') (whereas senate_event_to_row checks observed_at or checked). In real house.json.gz, 0/5,741 rows have imported_at and 5,741/5,741 have checked, making imported_at (the merge order_by column!) 100% NULL.
5. senate_events (sync_weekly_tables.py:103-110, senate.py:36-41): sync_weekly_tables passes the top-level senate.json.gz dict (keyed by 22 Senate domains like intelligence.senate.gov) to upsert_events, creating 22 rows with url=None and up to 24.48 MB in a single payload_json cell instead of per-page (5,232) rows.
6. captions (captions.py:57-74, sync_weekly_tables.py:112-119): Syncing inventory.json.gz produces 100% NULL outcome, observed_at (order_by), last_successful_json, and receipt_json for all 5,750 rows, while silently dropping the mods (2,137 rows), probes (3,268 rows), and witness_lists (8 rows) sections of inventory.json.gz.
7. Double Parquet serialization in WeeklyRetentionTables._operation_id (weekly_tables.py:515-520): writes the entire Arrow table as ZSTD Parquet into a BufferOutputStream just to compute a 16-char SHA-256 before serializing the table again for docspec-rs.

## Design

1. Fix all 5 broken row builders to extract from the real Pydantic model / cache shapes (videoId/publishedAt/videoPublishedAt, record['committee'] with key=('congress', 'system_code'), imported_at or checked, GpoEvidenceRecord listing/mods/transcripts, and per-page senate_events).
2. Normalize all 10 weekly_tables datasets into typed Arrow columns (eliminating 100%-duplicate payload_json in gpo_hearings and normalizing structured fields in youtube_videos, congress_committees, congress_meetings, house_events, senate_events, gpo_observations, captions + inventory sections, transcripts, and rejected_pages) while offloading raw bodies (upstream, source_bodies XML/HTML, Senate HTML/lines, GPO mods/transcripts, committee detail) to R2 via *_sha256 columns.
3. Add non-empty primary-key and merge order_by assertions in build_arrow_table / _upsert_batch.
4. Replace the in-memory pq.write_table in _operation_id with a fast digest over Arrow buffers or key+order_by columns.

## Acceptance Criteria

1. Syncing real pipeline-data into WeeklyRetentionTables preserves all 67,351 youtube_videos rows with non-empty video_id and published_at, all 3,424 congress_committees rows with non-null system_code/chamber/update_date, all 5,232 senate_events page rows with zero >256 KiB cells, and 100% non-null merge order_by columns across house_events and gpo_observations.
2. Raw upstream envelopes, XML/HTML source_bodies, and scraped page lines are offloaded to R2 via SHA-256 digests and all structured fields are normalized into typed Arrow columns.
3. _operation_id no longer performs a throwaway pq.write_table pass.


## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 80 → 80, work 66 → 66.
- Problem: Readers still select `payload_json`: house.py:54-59, senate.py:85-90, gpo.py:39-47,117-139.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:113
- Status: Closed as superseded by the simplification plan (WS10, ct-r6xw): WS10 deletes the weekly retention mirror after confirming nothing reads it.
- See docs/reviews/2026-10-24-ticket-audit/README.md
