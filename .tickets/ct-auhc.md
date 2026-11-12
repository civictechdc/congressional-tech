---
id: ct-auhc
status: closed
deps: []
links: [ct-x00f, ct-17op, ct-ly88]
created: 2026-11-11T09:47:37Z
type: feature
priority: 3
assignee: mikewolfd
tags: [engine, docspec-rs, lake, schema]
---
# Add an add-optional-column table operation to the engine so lake tables can gain nullable fields

Both appearance-record schema changes so far (2026-11-05, ea2cf179; and the MODS committees/committee_members fields 36-39 in 2026-11-11) needed a new table and a re-pin, because the pinned engine b0342a73 offers only Resolve, CreateNamespace, Create, Append and Purge (docspec-rs src/job/table_operations.rs:26-63) and Append refuses differing field names. Evidence: .cache/archive-release/investigations/mods-backfill-activation-20261111/ba-findings.md, ba-schema-probe. The release session will ask the refactor team whether the one-line engine (ct-x00f) already has such an operation, since that pin move comes first. Engine-first: this belongs in docspec-rs, not in CT code.

## Acceptance Criteria

The engine can add a nullable field to an existing lake table as a recorded table operation; appending rows with the new field to an older table works after it; a CT test shows a MODS-style two-column addition without a new table; old snapshots still read.


## Notes

**2026-11-11T09:48:23Z**

2026-11-11 (session congress-1, from the release session and the refactor team, read from source on engine candidate ae12bbd): the one-line engine cannot add a column to a pipeline lake table either (same five table operations; append still refuses a field-name mismatch). It has schema evolution only for the engine's own datasets (docspec schema / plan-schema), which does not serve appearance_records without moving the table into the dataset model. So the MODS fields 36-39 ship through a new table this release (option 1, the 2026-11-05 path). The refactor team scoped X9: a guarded add_columns table operation (optional columns only, fresh field ids, refuses a stale head, idempotent), as a post-pin engine item. The pipeline caller in packages/congress_api/src/congress_api/lake/tables.py is CT's.

**2026-11-11T14:30:07Z**

validated 2026-11-11, left open: X9 is built on engine branch dx/add-columns (bafd5c4, 6 commits) but is NOT merged into dx/one-line (8db7ebb; git merge-base --is-ancestor says no) and not in the pin candidate ae12bbd. Remains: review, merge onto the line, a later pin, and the CT caller in lake/tables.py with the MODS-style two-column test. The MODS fields 36-39 ship through a new table this release.

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green) and CT caller wiring on `claude/ct-wave-2-pin2`.
- Engine (`src/job/table_operations.rs`): merged & reviewed guarded `TableOperation::AddColumns` (`kind: "add_columns"`), assigning fresh Iceberg field IDs above `highest_field_id`, enforcing CAS against `expected_schema_id` (refusing stale heads), rejecting required/non-primitive/conflicting columns, and returning an idempotent no-op when all requested columns already exist with matching optional types.
- CT pipeline caller & tests (`packages/congress_api/src/congress_api/lake/tables.py` `add_optional_columns`, `packages/congress_api/tests/test_lake_tables.py::test_mods_style_two_column_addition_evolves_lake_table_in_place_and_filters_nullable_lists`): verified in-place MODS-style two-column addition (`title`, `created`), idempotent repeat at `expected_schema_id=1`, stale-head refusal at `expected_schema_id=0`, appending rows with the new fields, and reading both historical (`schema_id=0`) and head (`schema_id=1`) pins. Also verified end-to-end in the 5-hop horizontal raw-data slice trace cloning real R2 MODS record `CHRG-112hhrg72212` (`Janet Napolitano`).
