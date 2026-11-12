---
id: ct-p5m8
status: closed
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 3
assignee: mikewolfd
tags: [video, reader]
---
# Video titles and descriptions flip between empty, one space and trailing space across cache refreshes

Release 2026-11-10: 31 descriptions go NULL to one space, one gains two spaces (youtube:asMWWn5Ztvs), 8 descriptions and 4 titles gain a trailing space; YouTube's text is unchanged and the cache keeps whichever of two answers was fetched last. 1,064 whitespace-only descriptions are already live. Source: .cache/archive-release/release-20261110/causes/video/README.md.

## Acceptance Criteria

The video record reader normalises surrounding whitespace and maps whitespace-only text to null; the count of whitespace-only titles and descriptions in a build is 0.


## Notes

**2026-11-11T14:44:37Z**

validated 2026-11-11, left open: not fixed. DuckDB on 77673bfb8fcf videos.parquet: 1,095 source_description values are whitespace-only and 1,159 rows have a title or source_description with surrounding whitespace (0 whitespace-only titles).

**2026-11-12T04:34:00Z**

Closed: `model/sql/entity-videos.sql` now normalizes `title` and `source_description` via `nullif(regexp_replace(..., '^\s+|\s+$', '', 'g'), '')` over all retained `video_records` rows (handling ASCII and Unicode whitespace without moving pinned `video_records` producer versions or requiring an R2 lake backfill; clears all 1,095 whitespace-only descriptions and 1,177 Unicode-whitespace-padded rows measured on `46ebbdf8dcaf` `videos.parquet`). Added `untrimmed_video_texts` to `explorer_invariants` in `archive_model.py` so any empty or whitespace-padded `videos_export` text fails the model build.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
