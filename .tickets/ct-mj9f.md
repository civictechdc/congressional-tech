---
id: ct-mj9f
status: open
deps: []
links: [ct-m104, ct-sw5t]
created: 2026-11-03T00:59:39Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, bills, spicy-regs, phase2]
---
# Expand bills.parquet beyond hearing-referenced bills and publish popular/introduced titles and related vehicles

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, Briefs 1-5) uncovered two structural gaps in bills.parquet:
1. entity-bills.sql:1-5 restricts bills.parquet to referenced_bills (bills appearing in list.measure_keys or meetings.subject_keys, 10,352 rows). Major enacted laws and standalone oversight bills that bypassed a tagged committee hearing or moved as floor/omnibus vehicles—including 118-hr-815 (P.L. 118-50, TikTok divest-or-ban supplemental), 118-s-686 (RESTRICT Act), 118-s-2973 (Railway Safety Act), 117-s-3541 (Health Care for Burn Pit Veterans Act), 118-s-127, and 118-s-1339—are completely absent from bills.parquet.
2. On legislative shell vehicles such as 117-s-3373 (Sergeant First Class Heath Robinson Honoring our PACT Act of 2022, P.L. 117-168) and 117-hr-6833 (Continuing Appropriations and Ukraine Supplemental Appropriations Act, 2023), bills.title and bills.short_title retain only the pre-substitution shell title/committee or drop the introduced title, so searching bills for 'PACT Act' fails to match 117-s-3373.

## Design

Owner: model/sql/entity-bills.sql, model/registries/release-schema.json, and apps/explorer_mcp/src/congressional_explorer_mcp/reader.py.
1. Expand the candidate bill set in entity-bills.sql beyond referenced_bills to include all bills in spicy_congress_bills that are enacted, have floor votes (spicy_roll_call_votes / spicy_bill_vote_references), have CBO cost estimates (spicy_cbo_cost_estimates), or have committee activities (or all rows in spicy_congress_bills if within the release size budget).
2. Publish introduced_title, popular/short title variants (or ensure short_title prefers the enacted/popular short title while preserving introduced_title), and related_bills (vehicle/companion links) when available in upstream SpicyRegs bill-family tables.
3. Include any added title field in reader.py TEXT_FIELDS so search_entities(table='bills', text='PACT Act') resolves 117-s-3373.

## Acceptance Criteria

- Enacted and floor-voted bills (including 118-hr-815, 118-s-686, 118-s-2973, 117-s-3541) are published in bills.parquet.
- Shell vehicles (such as 117-s-3373 and 117-hr-6833) carry both their enacted/popular short title and introduced title so search_entities(table='bills', text='PACT Act') matches 117-s-3373.
- release-schema.json and docs/release-relationships.md document the updated bills.parquet scope and columns, and archive_schema --check passes.

