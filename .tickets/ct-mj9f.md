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
# Link unreferenced Senate original-bill markups and related bill vehicles to hearings and publish public_law_number + related_bills

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, Briefs 1-5) and follow-up investigation of user decision A2 ("shouldn't *all* bills be referenced by hearings in some way or form?") uncovered the exact hearing-linkage gaps explaining why certain bills missed meetings.subject_keys / bills.parquet:
1. Already in meetings.subject_keys and bills.parquet (13,234 rows in r1b-frozen/release): 118-s-127, 118-s-1339, 118-s-576, 117-s-3373, 117-hr-6833, and 118-hr-7521 ARE already linked to hearings and present in bills.parquet (they were only absent in the older 10,352-row publish_v21 snapshot prior to ct-h1nd / r1b).
2. Unlinked Senate original-bill markup meetings (subject_keys=[]): Both 118-s-2973 (Modernizing and Ensuring PBM Accountability Act) and 117-s-3541 (Health Care for Burn Pit Veterans Act) DO have markup meetings in meetings.parquet:
   - event_id=334680 (2023-07-26, ssfi00): 'Business meeting to consider an original bill entitled, "Modernizing and Ensuring PBM Accountability (MEPA) Act".' (subject_keys=[])
   - event_id=331760 (2022-02-02, ssva00): 'Business meeting to consider an original bill entitled "Health Care for Burn Pit Veterans Act".' (subject_keys=[])
   Across meetings.parquet, 28 Senate business meetings marking up "an original bill entitled '...'" have subject_keys=[] because Senate original bills are assigned their S. XXXX bill number only when the committee reports the bill to the floor (recorded in spicy_bill_committee_activities as 'Reported by' after the markup date), and Congress.gov never back-fills the assigned bill number onto the original meeting's relatedItems.
3. Related bill / enacted omnibus vehicles of hearing-referenced bills: 118-hr-815 (P.L. 118-50, TikTok divest-or-ban supplemental) is the enacted vehicle in spicy_congress_bills.related_bills for 118-hr-7521 (Protecting Americans from Foreign Adversary Controlled Applications Act, which IS in meetings.subject_keys on event_id=116945 and list.measure_keys), and 117-hr-6833 is the vehicle linked in related_bills to 117-s-3700 (Affordable Insulin Now Act). Currently SPICY_SCHEMAS['spicy_congress_bills'] in archive_model.py:138-143 omits public_law_number, cosponsor_count, and related_bills, and entity-bills.sql does not include related_bills vehicles or bills with non-referral committee action in spicy_bill_committee_activities.

## Design

Owner: model/sql/meeting-records-resolved.sql, model/sql/entity-meetings.sql, model/sql/entity-bills.sql, packages/viewer_publication/src/viewer_publication/archive_model.py (SPICY_SCHEMAS), model/registries/release-schema.json, and apps/explorer_mcp/src/congressional_explorer_mcp/reader.py.
1. Reconcile meetings.subject_keys from all 5 authoritative in-corpus sources (User Decision A2 + /etl-workflow Audit F3, F4, F5; bounded probe verified on r1b-frozen + spicy_regs):
   - Source A (1:1 (committee, activity_date) Hearings/Markup in spicy_bill_committee_activities — +438 meetings, +1,200 bills): When spicy_bill_committee_activities records activity_name ILIKE 'Hearings%' OR activity_name ILIKE 'Markup%' on (system_code, activity_date) and exactly 1 meeting in meetings_resolved matches that (committee/parent_committee, meeting_date), union bill_id into meetings.subject_keys.
   - Source B (Senate/House "original bill entitled '...'" markups — +25 meetings, +42 original bills including 334680 -> 118-s-2973 and 331760 -> 117-s-3541): Extract titles after 'original bill entitled' (stripping trailing parenthetical acronyms like '(MEPA)') and match against spicy_congress_bills + spicy_bill_committee_activities on the same (congress, committee/parent_committee) and normalized title/short_title.
   - Source C (Single-meeting document measure_keys — +96 meetings, +300 bills): When a document in ordered has len(meeting_keys) = 1 and non-empty measure_keys, union its measure_keys into that meeting's subject_keys in entity-meetings.sql. (Do NOT reverse-propagate meetings.subject_keys into list.measure_keys: release-schema.json and test_relationships.py:141 define list.measure_keys strictly as direct document annotations.)
   - Source D (Confirmation hearing transcripts in nominations.transcripts[] — +20 meetings, +23 nominations): Union nomination_id into meetings.subject_keys when nominations.transcripts[] matches a package_id in meetings.transcripts.
   - Source E (Explicit bill numbers in meetings.title — +266 meetings, +858 bills): Extract explicit bill citations (H.R., S., H.J.Res., S.J.Res., H.Con.Res., S.Con.Res., H.Res., S.Res. after stripping 'U.S.') from meetings.title, normalize to {congress}-{type}-{number}, and validate against spicy_congress_bills.bill_id before unioning into meetings.subject_keys.
2. Include committee-action bills and related_bills vehicles of hearing-referenced bills in entity-bills.sql:1-5 (within DataFusion's 109.6 MB aggregate memory cap):
   - Union referenced_bills (from list.measure_keys and the enriched meetings.subject_keys) with: (a) related_bills vehicles referenced by any hearing-referenced bill (e.g. 118-hr-815 <-> 118-hr-7521, 117-s-3700 <-> 117-hr-6833); and (b) bills with committee action beyond mere referral in spicy_bill_committee_activities (activity_name NOT ILIKE 'Referred%' — including 'Reported original measure', 'Reported by', 'Markup by', 'Hearings by') or present in spicy_cbo_cost_estimates / spicy_roll_call_votes / public_law_number IS NOT NULL / coalesce(cosponsor_count, 0) >= 10 for congress >= 113.
3. Add public_law_number, cosponsor_count, and related_bills to SPICY_SCHEMAS['spicy_congress_bills'] in archive_model.py:138-143, project them in entity-bills.sql (with coalesce(..., []) on non-null list columns per archive_schema.py:248-254), and declare them in model/registries/release-schema.json.
4. Add 'public_law_number' to TEXT_FIELDS in apps/explorer_mcp/src/congressional_explorer_mcp/reader.py:14-15.

## Acceptance Criteria

- Senate original-bill markup meetings (including 334680 -> 118-s-2973 and 331760 -> 117-s-3541) populate meetings.subject_keys and resolve in get_entity(table='bills', id=..., section='meetings').
- Hearing-referenced bills, their related_bills legislative vehicles (including 118-hr-815 <-> 118-hr-7521 and 117-hr-6833 <-> 117-s-3700), and committee-action/substantive 113th-119th Congress bills (including 118-s-686) are published in bills.parquet with public_law_number, cosponsor_count, and related_bills while staying within DataFusion's 109.6 MB per-stream aggregate memory cap and null_bills_* = 0 in relationship_invariants.
- release-schema.json and docs/release-relationships.md document the updated bills.parquet scope and columns, and archive_schema --check passes.

