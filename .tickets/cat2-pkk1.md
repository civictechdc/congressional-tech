---
id: cat2-pkk1
status: open
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

