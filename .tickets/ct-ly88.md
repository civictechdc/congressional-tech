---
id: ct-ly88
status: closed
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


## Notes

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green).
- Engine root-cause fix (`docspec-rs` commit `0e45e1c` in `src/job/native.rs` `AdmittedTable::supports_filters_pushdown`): inspects pushed `Expr` filter trees recursively and marks any filter referencing a non-primitive or nested `List` / `LargeList` / `FixedSizeList` / `Map` / `Struct` column (including `IS NULL`, `IS NOT NULL`, boolean conjunctions, and negations) as `TableProviderFilterPushDown::Unsupported` so DataFusion evaluates it cleanly above the scan while primitive column pushdown stays `Inexact`.
- Regression coverage: reproduced & verified in `docspec-rs` (`tests/sql_table_jobs.rs`), in CT (`packages/congress_api/tests/test_lake_tables.py::test_mods_style_two_column_addition_evolves_lake_table_in_place_and_filters_nullable_lists`), and directly against the live R2 Iceberg table `archive_r1b.appearance_records_committees_20261111` (`table_uuid = 01a1cbde-6504-7571-b83b-19d9ef114596`, snapshot `4037276441541016815`, returning `CHRG-112hhrg72212` for `committees IS NOT NULL AND held_dates IS NOT NULL` and `327,721` rows for `committees IS NULL`; `.cache/archive-release/release-20261112-pin2/benchmarks/verify_horizontal_slice.py`).

