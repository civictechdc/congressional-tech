---
id: ct-ly88
status: open
deps: []
links: [ct-auhc]
created: 2026-11-11T19:08:57Z
type: bug
priority: 2
assignee: mikewolfd
tags: [engine, docspec-rs, iceberg, lake]
---
# Engine: IS [NOT] NULL on a nullable list column fails when pushed into the Iceberg scan ('Accessor for Field … not found')

Found 2026-11-11 when the MODS appearance activation's post-import compare failed on the new table archive_r1b.appearance_records_committees_20261111: 'query: External error: DataInvalid => Accessor for Field committees not found'. Cause (diagnosis .cache/archive-release/investigations/mods-backfill-activation-20261111/ba-probe-local/probe.json, ba-findings.md): iceberg-datafusion 0.10.1 pushes IS NULL / IS NOT NULL down into the scan (expr_to_predicate.rs:124-133); iceberg 0.10.1 then looks the column up in an accessor map (src/expr/term.rs:325-330) that only covers primitive and struct columns (spec/schema/mod.rs:189-200), so any nullable list column fails. Pre-existing: on the old table head 00010, 'held_dates IS NOT NULL' fails the same way; 'appearances IS NOT NULL' passes only because appearances is required and the planner drops the filter. Data and import are correct (projection of all 15 columns and the same filter on a materialized step both work; the import's verify reads every column via SELECT * EXCEPT ALL but applies no filter). No CT model SQL puts such a predicate on a list column today (grep), so releases are not blocked; the compare script now filters a materialized step. Owner: fix at the root: in docspec-rs (do not push NULL predicates on non-primitive fields into the Iceberg scan, or move to an iceberg release that supports them), with a test reproducing this; refactor team.

## Acceptance Criteria

docspec-rs: a query with IS NULL / IS NOT NULL on a nullable list column of a lake table returns correct rows; a regression test reproduces the 2026-11-11 failure; CT pins the fixed engine.

