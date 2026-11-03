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

Owner: model/sql/entity-rosters.sql, model/jobs/publish-model.json (or upstream spicy-regs pin binding), and model/registries/release-schema.json.
1. Bind the multi-Congress spicy_committee_assignments snapshot from spicy-regs (covering 113th-119th Congresses, including Chair, Ranking Member, and Vice Chair role titles across full committees and subcommittees) into the model input pin.
2. Verify in entity-rosters.sql that system_code normalization (including House select/task-force codes hs* -> hl*/ht* per AGENTS.md) aligns historical roster rows with committees.parquet (missing_committee_keys = 0).
3. Update the rosters.parquet coverage/gap notes and upstream_relations.committee_assignments limits in model/registries/release-schema.json and regenerate docs/release-relationships.md.

## Acceptance Criteria

- rosters.parquet publishes committee and subcommittee seat assignments across the 113th-119th Congresses (including Chair and Ranking Member titles), verified by committee_roster recipe queries on historical Congresses (e.g. congress=116, 117, 118).
- All rosters.system_code values resolve against committees.parquet (missing_committee_keys = 0) and bioguide_id values resolve against members.parquet.
- release-schema.json and docs/release-relationships.md reflect multi-Congress roster coverage, and archive_schema --check passes.

