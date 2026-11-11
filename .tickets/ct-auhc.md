---
id: ct-auhc
status: open
deps: []
links: [ct-x00f]
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

