---
id: cat2-8ai9
status: open
deps: []
links: [ct-jcnd, ct-ywz2, ct-yizl]
created: 2026-11-12T12:20:24Z
type: bug
priority: 0
assignee: mikewolfd
tags: [model, meetings, recordings, dates, horizontal-audit]
---
# Horizontal audit model integrity: m3u8 caption honesty, canonical list.witness_keys, plausible date precedence, soft-404 .pdf hides, and shell meeting backfill

From the 22-slice horizontal raw-data audit (P0-2 SQL, P1-5 SQL, P1-6 SQL, P1-8 SQL, P2-10a SQL): (1) entity-meetings.sql marks 657 Senate hearings with format='m3u8' HLS playlists (0 words of text, unpublished caption_resources) as captions.archived=1 / retained_track; (2) document-witness-keys.sql unions 71,913 superseded witness keys (43.0% of links) into list.witness_keys; (3) document-normalized.sql lets suspect filename_date (2031-01-19 on 295289, 1901-09-26 on 7870) override valid content_date/meeting_date and omits document_date_status from list.parquet; (4) 5 retained HTML 404 error pages saved under .pdf names (262153, 271440, 278019, 278840, 278874) publish visible as amendments/testimony, and 77 descriptions retain double-escaped &#39;/&quot;/&amp;; (5) 546 shell meetings (e.g. 100166) publish with null chamber/congress/committees/meeting_date despite unambiguous linked documents.

## Acceptance Criteria

m3u8 playlists without retained caption_resources report advertised_not_archived; list.witness_keys holds canonical keys only; plausible dates beat suspect filename_date; HTML 404 .pdf impostors hidden and entities decoded; unambiguous shell meetings backfilled from linked documents.

