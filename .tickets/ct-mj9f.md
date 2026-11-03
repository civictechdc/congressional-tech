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
# Expand bills.parquet beyond hearing-referenced bills and publish public_law_number and related_bills vehicles

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, Briefs 1-5) and Red/Green Team audit of spicy_congress_bills (422,024 rows in f719442c...) uncovered two gaps in bills.parquet:
1. entity-bills.sql:1-5 restricts bills.parquet to referenced_bills (bills appearing in list.measure_keys or meetings.subject_keys, 10,352 / 13,234 rows). Major enacted laws and standalone oversight bills that were not directly tagged on a committee hearing—including 118-hr-815 (P.L. 118-50, TikTok divest-or-ban supplemental), 118-s-686 (RESTRICT Act, cosponsor_count=55), 118-s-2973 (Modernizing and Ensuring PBM Accountability Act, stage='calendared'), 117-s-3541 (Health Care for Burn Pit Veterans Act, stage='passed_one', CBO estimate), 118-s-127, and 118-s-1339—are absent from bills.parquet. (Note: 117-s-3373 already has short_title='Honoring our PACT Act of 2022' in bills.parquet and resolved once ct-sw5t added short_title to reader.py TEXT_FIELDS.)
2. On legislative shell/omnibus vehicles such as 117-hr-6833 (Continuing Appropriations and Ukraine Supplemental Appropriations Act, 2023, originally the Affordable Insulin Now Act shell) and 118-hr-815 (P.L. 118-50, vehicle for 118-hr-7521 TikTok mandate), spicy_congress_bills has no introduced_title column, but DOES carry public_law_number ('118-50', '117-168', '117-180'), cosponsor_count, and related_bills (STRUCT(bill_type, congress, latest_action_date, latest_action_text, number, relationship_details, title)[], which links 118-hr-815 <-> 118-hr-7521 and 117-hr-6833 <-> 117-s-3700 'Affordable Insulin Now Act'). Currently SPICY_SCHEMAS['spicy_congress_bills'] in archive_model.py:138-143 omits public_law_number, cosponsor_count, and related_bills.

## Design

Owner: model/sql/entity-bills.sql, packages/viewer_publication/src/viewer_publication/archive_model.py (SPICY_SCHEMAS), model/registries/release-schema.json, and apps/explorer_mcp/src/congressional_explorer_mcp/reader.py.
1. Expand referenced_bills in entity-bills.sql:1-5 to include substantive bills without blowing DataFusion's 109.6 MB GroupedHashAggregateStream memory cap (do NOT include all 167k-280k routine 'Referred to' rows from spicy_bill_committee_activities unfiltered): union referenced_bills with spicy_congress_bills rows where try_cast(congress AS INT) >= 113 AND (stage NOT IN ('introduced', 'committee') OR public_law_number IS NOT NULL OR coalesce(cosponsor_count, 0) >= 10) plus bills present in spicy_cbo_cost_estimates, spicy_roll_call_votes, or spicy_bill_vote_references (~31k-37k bills, capturing 118-hr-815, 118-s-686, 118-s-2973, 117-s-3541, 118-s-127, 118-s-1339).
2. Add public_law_number, cosponsor_count, and related_bills to SPICY_SCHEMAS['spicy_congress_bills'] in archive_model.py:138-143, project them in entity-bills.sql (with coalesce(..., []) on non-null list columns per archive_schema.py:248-254), and declare them in model/registries/release-schema.json.
3. Add 'public_law_number' to TEXT_FIELDS in apps/explorer_mcp/src/congressional_explorer_mcp/reader.py:14-15.

## Acceptance Criteria

- Substantive 113th-119th Congress bills (including 118-hr-815, 118-s-686, 118-s-2973, 117-s-3541, 118-s-127, 118-s-1339) are published in bills.parquet while staying within DataFusion's 109.6 MB per-stream aggregate memory cap.
- bills.parquet publishes public_law_number, cosponsor_count, and related_bills (connecting omnibus/shell vehicles like 118-hr-815 -> 118-hr-7521 and 117-hr-6833 -> 117-s-3700), with null_bills_* = 0 in relationship_invariants.
- release-schema.json and docs/release-relationships.md document the updated bills.parquet scope and columns, and archive_schema --check passes.

