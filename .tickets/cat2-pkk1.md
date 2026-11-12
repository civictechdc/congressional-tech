---
id: cat2-pkk1
status: closed
deps: []
links: [ct-46f3, ct-esuu, ct-kt2o, ct-egoo]
created: 2026-11-12T12:20:24Z
type: bug
priority: 1
assignee: mikewolfd
tags: [site, mcp, nominations, witnesses, horizontal-audit]
---
# Horizontal audit site & Explorer MCP: record_sha hex, m3u8/recordings honesty, partitioned nomination URLs & activities, 2027 date cliff, package_id witness links, UUID PDF labels, and retired address_versions labels

From the 22-slice horizontal raw-data audit (P1-4, P0-2 MCP, P2-10d MCP, P1-7 UI/MCP, P1-6 UI, P0-1 UI, P2-9 UI, F5 UI/MCP): (1) Explorer MCP get_hearing_bundle emits raw escaped binary bytes for witnesses.record_sha BLOB; (2) MCP hearing_reader.py counts bare m3u8 as readable captions and returns duplicate video_key rows + congress.gov/event/ HTML URLs in recordings; (3) 736/783 partitioned nominations (e.g. 119-pn-1022-10) link to broken /1022-10 on site and /1022 + '101th-congress' in MCP legislative_reader.py, while SubjectDetail.tsx hides all nomination committee_activities; (4) archive.ts hardcodes 2026-12-31 maxPlausibleDateEpoch (49-day cliff for 2027) and ArchiveRows.tsx omits (likely misread) on suspect dates; (5) WitnessDetail.tsx renders empty 'Hearing ' stubs on historical MODS witnesses (event_id=null, package_id set) and archive-metadata.ts shows raw 36-char UUIDs as bold titles on 487 untitled Senate PDFs; (6) retired multi-part notices (?key=cb0383af1fd10c1e) show raw 16-hex address_versions keys (58cc6f3f89fac200, a7b7aa76c6268c40) instead of resolving part filenames from loaded links+list.

## Acceptance Criteria

All 6 site & Explorer MCP cross-surface defects fixed with unit + Playwright/MCP assertions; F2 5-group document_kind synonym parity covered by explicit regression test.


## Closeout Note (2026-11-12)

Shipped in `claude/ct-wave-5-identity`:
1. **`P1-4` (`hearing_reader.py`):** Converted `witnesses.record_sha` via `lower(hex(record_sha))` instead of raw escaped binary bytes.
2. **`P0-2` & `P2-10d` (`hearing_reader.py`):** Excluded bare `.m3u8` HLS playlists without readable VTT/SRT text from `archived` caption counts, deduplicated `video_key` rows, and excluded `congress.gov/event/` HTML landing pages from recording URLs.
3. **`P1-7` (`archive-metadata.ts`, `SubjectDetail.tsx`, `legislative_reader.py`):** Fixed partitioned nomination Congress.gov URLs (preserving partitioned `/nomination/{ordinal}-congress/{number}/{part}` URLs), fixed `11th`/`12th`/`13th`/`101st` ordinals in `legislative_reader.py`, and rendered compact nomination `committee_activities` in `SubjectDetail.tsx`.
4. **`P1-6` (`archive.ts`, `ArchiveRows.tsx`):** Replaced hardcoded `2026-12-31` cliff with dynamic `max(now, capture) + 30 days` (`computeMaxPlausibleDateEpoch`) and surfaced `(read from the filename; likely misread)` on suspect list-row dates via `dateLabels(row, row)`.
5. **`P0-1`, `P1-5`, & `P2-9` (`archive-entities.ts`, `WitnessDetail.tsx`, `archive-metadata.ts`):** Enriched `event_id == null` MODS witnesses via `package_id` (`meetings.transcripts[]`), resolved superseded witness keys on lookup, and replaced raw 36-char Senate PDF UUID titles with readable congressional context labels.
6. **`F5` & `F2` (`archive-worker.ts`, `archive.ts`, `ArchiveDetail.tsx`, `reader.py`, `kind-synonyms.test.ts`):** Resolved retired multi-part `address_versions` hex keys to human-readable part filenames (`versionItems`), added `'identity_note'` to `corrections` search in `reader.py`, and locked 5-group `document_kind` synonym parity between `release-schema.json`, `apps/site`, and `apps/explorer_mcp`.
