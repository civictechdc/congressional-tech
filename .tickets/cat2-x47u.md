---
id: cat2-x47u
status: open
deps: []
links: [ct-jcnd, ct-lft6, ct-esuu, ct-5q3g]
created: 2026-11-12T12:20:24Z
type: bug
priority: 0
assignee: mikewolfd
tags: [model, titles, mods, chrg, horizontal-audit]
---
# Horizontal audit model documents: join package_mods_facts on CHRG prints, strip leading '- ' titles, prefer <h1> over generic/truncated <title>, and classify BILLS-*-RCP* prints

From the 22-slice horizontal raw-data audit (P0-1 SQL, F3, P2-9 SQL, F4 SQL): (1) document-normalized.sql never joins package_mods_facts on 35,965 CHRG-* rows (71% lack chambers/committee_keys/document_date; 100% have witness_keys=[]; CHRG-118hhrg57786 MODS witnesses have event_id=null despite unambiguous meeting_keys=['116980']; jcse00 Joint Commission lacks chambers=['joint']; accepted document_date leaves congress=null on 318088); (2) 34,809 published titles (33,958 other_format_page_title + 851 page_title) retain GPO HTML <title>'s literal leading '- ' prefix in Parquet & MCP (masked on website by archive-metadata.ts:1364 and enshrined in test_titles.py:69); (3) source-annotations-final.sql prefers generic ('hearing | Hearings | ...') or '...'-truncated <title> over clean <h1>, and page-signals.json lacks 'hearing' link_word / accepts split '^_[0-9]' anchors; (4) 176 BILLS-*-RCP* Rules Committee Prints classify as bill-measure-list / list instead of committee-print / print.

## Acceptance Criteria

All 4 SQL/registry gaps fixed with unit & model regressions: CHRG-* rows inherit MODS date/committees/chamber/congress/title/canonical witness_keys and unambiguous package_id->event_id witness link; 0 published titles start with GPO leading '- '; <h1> beats generic/truncated <title> and split/stopword anchors drop; BILLS-*-RCP* rows classify as committee-print / print.

