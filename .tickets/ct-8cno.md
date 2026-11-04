---
id: ct-8cno
status: open
deps: []
links: [ct-m104, ct-itcg, ct-mx3g]
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

**2026-11-04T15:07:16Z**

2026-11-04 accountability investigation: missing upstream history still blocks historical normalization. Live release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; checkout inspected separately at 730a2d8e0c55880fc058d13cc74d265fc315f41f. This is ticket-only follow-up to chaos-personas-20261104; no repair, tests, source regeneration or publication was performed. Fresh runtime schema is retained in .cache/archive-release/chaos-personas-20261104/ticket-accountability/runtime-check.json.

For e4538f00 the independent roster count remains 2,973 rows, Congress 119 only; the fresh runtime metadata agrees. The normalized hearing-count query has matching rosters for 148 of 188 committee associations with hearings in Congress 119, and cannot normalize Congresses 112–118. Evidence: .cache/archive-release/chaos-personas-20261104/independent-table-audit.json; accountability/calls.jsonl call 55; investigation-accountability/cases.json P3Q1. The 148/188 figure is committee associations in that query population, not proof those unmatched committees should all have seats.

Current model/sql/entity-rosters.sql:27-40 reads, deduplicates and retains supplied Congress values from spicy_committee_assignments; it cannot synthesize history absent from its pinned generation. Verified upstream dependency remains open /Users/mikewolfd/Work/spicy-stack/.tickets/ss-ehci.md: dated source-catalog-selected roster captures on main's roster implementation, explicit read failures, and built/published per-Congress history. Its owner decision retires the old branch prototype. Treat that current upstream plan as authoritative rather than reviving the superseded branch/YAML approach from this ticket's older Design prose.

Smallest remaining acceptance: finish and publish ss-ehci's dated history, pin that generation, retain the existing key/reference invariants, qualify/publish archive output, then demonstrate historical committee_roster queries against the installed selected release. The persona's 112th-Congress request lies outside the stated 113th–119th schema-support span and needs a separate source/coverage decision; this ticket does not silently promise it. Correcting ct-mx3g's wording is independent from acquiring history. Preserve status open; no data or pin changes were made.

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Owner split: open spicy-stack ss-ehci supplies dated source-catalog-selected roster history on main; archive entity-rosters.sql:27-40 retains supplied Congress values, deduplicates and exports them. The retired branch prototype is not an implementation base. Preserve literal source Congress, dated provenance, per-Congress committee/member multiplicity and explicit failed-read/missing-history outcomes; do not infer Congress from URLs or fabricate the persona's unsupported 112th data.

Hard dependency: an accepted, published upstream history generation before changing the archive input pin and claiming 113th-118th roster availability. Keep current 119-only data/status explicit while that is unresolved. Archive fixture/key/reference checks and wording acceptance can proceed in parallel; ct-mx3g truthful metadata does not wait for acquisition. Add only representative historical/current and absent-history cases to maintained tests; reference-key parity and no duplicate committee/member seat assertions remain required.

Once the upstream generation exists, record its exact pin/delta and affected archive dependency closure, reuse unchanged records/completions, and measure expected memory/scratch/work before a heavy run under the existing watchdog. No broad raw scan, backfill or performance claim is authorized by this plan. Closure requires source-history evidence, native roster invariant/parity, qualified publication and actual committee_roster queries against the installed selected release, not schema support or local SQL alone.
