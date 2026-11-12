---
id: cat2-x47u
status: closed
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

## Notes

**2026-11-12:** Closed on `claude/ct-wave-4-model`:
- Joined `package_mods_facts` (mapped through `committee_codes`) in `document-normalized.sql` and `document-recovery-normalized.sql`, backfilling `document_date`, `committee_keys`, `chambers` (from `committee_keys` `^h`/`^s`/`^j` + `CHRG-[0-9]{1,3}([hsj])hrg`, fixing `jcse00`/`jjec00` Joint Commission rows and `CHRG-*` prints), `congress` fallback from accepted `document_date`, rank-5 `mods_title` (`titles.sql`), package `witness_keys` (`document-witness-raw-matches.sql`), and vetted single-day `CHRG-*` print->`event_id` links (`meeting-transcript-links.sql`).
- Stripped GPO leading `^\s*[-–—]+\s+` prefixes in `source-annotations-pages.sql` and `titles.sql` (`rank > 0`).
- Preferred clean `<h1>` (`page_heading`, stripping Senate ColdFusion SR-only `'Hearing status...: Hearing title...'`) over generic (`hearing | Hearings | ...`, bare committee banner) or `... |`-truncated `<title>` in `source-annotations-final.sql`, `document-recovery-normalized.sql`, and `recovered-copy-fills.sql`; added `hearings?` and split `^_[0-9]+` anchors to `model/registries/title-rules.json`.
- Classified `BILLS-*-RCP*` as `document_kind = ['committee-print']`, `document_family = ['print']` (`source-annotations-final.sql`) and extracted `'Rules Committee Print ...'` titles from `<amendment-doc>` XML `text_head` (`source-annotations-pages.sql`).

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
