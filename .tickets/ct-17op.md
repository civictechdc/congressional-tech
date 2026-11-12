---
id: ct-17op
status: closed
deps: []
links: [ct-wy4c, ct-6mvl, ct-auhc, cat2-ddas, ct-lft6]
created: 2026-11-11T14:57:19Z
type: feature
priority: 2
assignee: mikewolfd
tags: [parser, witnesses, mods, schema]
---
# Keep witness military rank and credentials in their own fields instead of dropping them

Owner decision 2026-11-10 (questions dialog, recorded on ct-wy4c): rank and credentials go in their own field, not in the name and not dropped. The follow-up parser work was said to join ct-6mvl's version step, but ct-6mvl does not mention it and the MODS witness-list branch (claude/ct-mods-zs48-3aap, shipping 2026-11-11) adds no such field (found by the release session's ticket audit 2026-11-11). Measured on ct-wy4c: after ct-rg34, 299 more MODS witness rows no longer show a rank or credential (47 rank, 291 credential); the live release already drops rank on 944 rows and credentials on 6,474 across sources. Nothing is lost in raw. Note: appearance-people.sql drops credentials and ranks as words for its same-person key; that is a keying choice and stays. Scope: every appearance producer that strips a rank or credential (find where each does), two new nullable fields in the appearance records and the published witnesses table (e.g. rank, credentials as stated), the release schema text, and the site/Explorer display. A new lake column needs a new table today (the pinned engine cannot add columns: see ct-auhc, the refactor team's X9 add_columns); fold it into the next appearance schema change or the first one after X9.

## Acceptance Criteria

Every row whose raw line states a rank or credential carries it in the new field, verbatim as printed (normalized spacing only); names no longer contain them; counts per source match a raw check reading the raw lines independently, both directions, with plants (a rank left in a name; a credential dropped); removals 0 against the live generation; the owner's decision cited.

## Notes

**2026-11-12T15:50:00Z**

Wave 3 (`claude/ct-wave-3-parsers`): added nullable `rank` and `credentials` across all 4 `appearance_records` producers (`mods`, `senate_page`, `house_xml`, `congress_gov`), `witnesses.parquet`, `release-schema.json`, Explorer MCP `Reader`, and `apps/site` (`WitnessDetail.tsx`, `ArchiveDetail.tsx`, `archive-entities.ts`), plus cross-hop fixes (`P0-3c` decomposed `<span class="fn"><span>Dr.</span>` honorific + leading `position` credential/branch peel in `senate_page.py`, `P0-3d` structured `family`/`given`/`suffix` consistency in `house_xml`, `P0-3e` civil honorific stripping into `honorific` across `congress_gov` and `house_xml`, and `witness-member-facts.sql` chamber-in-honorific preservation). Full raw-backed corpus (`66,490` records / `177,472` occurrences; `0` removals): `6,325` ranks (`mods: 2,947`, `congress_gov: 1,515` [`3,031` across full `36,438`-record table], `senate_page: 1,163`, `house_xml: 700`) and `14,047` credentials (`mods: 10,621`, `senate_page: 1,870`, `house_xml: 811`, `congress_gov: 745` [`1,480` full]); `36,037/36,037` `congress_gov` equivalence checks passed (`0` mismatches); `witness_ranks_credentials_raw_check.py` passed (`failed={}` unplanted; `4/4` plants caught); verified end-to-end through MCP & Playwright DOM (`wave3_horizontal_slice_review.md` slices `H1..H4`, `H8`). Ready for Merge Slot #1 + R2 `appearance_records` backfill.


