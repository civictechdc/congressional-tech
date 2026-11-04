---
id: ct-8cno
status: open
deps: []
links: [ct-m104, ct-itcg]
created: 2026-11-03T01:00:02Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, rosters, spicy-regs, phase2]
---
# Wire historical (113th-118th Congress) committee and subcommittee rosters into rosters.parquet

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, Briefs 1-5) found that rosters.parquet in both publish_v21 and r1b-run contains only congress=119 (2,487 rows), with 0 rows for the 113th-118th Congresses. Although ct-u01c (ss-vhi2) was closed on 2026-10-30 after adding historical roster support in spicy-regs (commit 45903e87), the archive model's pinned spicy_committee_assignments input and release-schema.json:3675 ('Current Congress only: not a historical roster') still export only the 119th Congress. Consequently, any historical oversight query (2014-2024) asking who chaired or sat on a committee/subcommittee at the time of a hearing returns 0 rows.

## Design

Owner: upstream spicy-regs build_committee_rosters.py (or historical roster ingestion), model/sql/entity-rosters.sql, model/sql/entity-committees.sql, packages/viewer_publication/src/viewer_publication/archive_model.py, model/jobs/publish-model.json, and model/registries/release-schema.json.
1. Upstream data generation & pin (User Decision A4 Confirmed): Verified that .cache/archive-release/r1b/inputs/spicy_regs/generations/committee-rosters/5f031073.../committee_assignments.parquet contains only congress='119' (2,973 rows) because spicy-regs build_committee_rosters.py (_historical_assignment_rows) only reads historical XML snapshots if present in SPICY_RAW_ARCHIVE_URI. Backfill 113th-118th Congress committee and subcommittee assignments (including Chair, Ranking Member, Vice Chair titles) in spicy-regs build_committee_rosters.py from unitedstates/congress-legislators (committee-membership-historical.yaml) into a new committee-rosters generation and update spicy-regs.json, model/jobs/publish-model.json:39-43, and model/jobs/publish.json.
2. Primary-key deduplication & non-null guards in model/sql/entity-rosters.sql:
   - Deduplicate on (congress, system_code, bioguide_id) (e.g. ROW_NUMBER() OVER (PARTITION BY congress, norm_system_code, bioguide_id ORDER BY ...)) so mid-Congress role changes never violate relationship_invariants.invalid_rosters_key == 0 (archive_schema.py:259-261).
   - Ensure rank and party are non-null (coalescing party from spicy_members when absent and synthesizing/preserving rank if required columns are non-null in release-schema.json).
3. Reference-key parity: Normalize system_code in entity-rosters.sql through committee_codes (hs* -> hl*/ht* per AGENTS.md), ensure all referenced committee codes (including hlig*, slin*, scnc00, and historical 113th-118th committees) exist in committees.parquet, and add rosters_export to missing_committee_keys / missing_member_keys checks in archive_model.py:1047-1065.
4. Update rosters.parquet coverage/gap notes and upstream_relations.committee_assignments limits in model/registries/release-schema.json, update apps/explorer_mcp/tests/test_relationships.py:20 in lockstep, and regenerate docs/release-relationships.md.

## Acceptance Criteria

- rosters.parquet publishes committee and subcommittee seat assignments across the 113th-119th Congresses (including Chair and Ranking Member titles), verified by committee_roster recipe queries on historical Congresses (e.g. congress=116, 117, 118).
- All rosters.system_code values resolve against committees.parquet (missing_committee_keys = 0) and bioguide_id values resolve against members.parquet.
- release-schema.json and docs/release-relationships.md reflect multi-Congress roster coverage, and archive_schema --check passes.


## Notes

**2026-11-03T12:48:59Z**

SQL, schema, and invariants implemented and verified on r3-mcp / release-train (4d583687): (congress, system_code, bioguide_id) deduplication, hs* -> hl*/ht* normalization including parent_system_code in entity-committees.sql, Congress-overlapping term party attribution and collision-free rank offsets in entity-rosters.sql, and missing_member_keys == 0 check in archive_model.py. Remaining step to close: publish and pin upstream spicy-regs committee-rosters generation containing 113th-118th Congress assignments in model/jobs/publish-model.json.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): rosters.parquet in live e4538f00 has congress 119 only (2,973 rows). The archive-side SQL landed (3a91ee98); 113-118 history is blocked upstream on spicy-stack ss-ehci (dated roster captures per Congress on spicy-regs main; the earlier branch prototype was retired by owner decision 2026-10-30).
