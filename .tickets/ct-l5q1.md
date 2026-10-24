---
id: ct-l5q1
status: closed
deps: []
links: [ct-7uit]
created: 2026-10-20T02:20:21Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Prove the change-storage boundary on one retained package

The current source pipeline has a capture cursor, but durable dependency state is rebuilt inside a disposable workspace. Establish the smallest shared input/version boundary needed by the raw, catalog and delivery lanes before they invent incompatible formats.

## Design

Use one existing GovInfo package plus a correction, deletion and alias-edge edit as the local slice. Inspect the current maintained DocSpec admission/change/completion interfaces and existing R2 conditional manifests. Select a demonstrated owner for dataset versions and completed work; name any missing capability. Do not build a general event engine or silently resume the postponed DocSpec migration.

## Acceptance Criteria

- Pin current code and retain a small semantic reference before changes, including duplicate occurrences, null/empty values, exact receipt locators and nested provenance.
- Produce executable boundary examples for stable operation keys, exact base versions, changed record keys, deletions, old/new dependency edges and explicit transform versions.
- Round-trip one retained package and its changes through the chosen maintained boundary; demonstrate restart and unchanged-input reuse. Document the exact supported API, not a speculative adapter.
- Record baseline read/write/validation counters and the consumer changes required in raw_archive, corpus_recovery, raw_catalog and catalog_publication. Reuse these examples in downstream tests.
- Stop at this boundary: no production migration, new scheduler, classifier change or broad Rust rewrite. Unsupported behavior gets a concrete capability finding, not a full-rebuild fallback.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch czsd).
- Grades: proposal 87 → 87, work 83 → 83.
- Problem: The 3 tests check only that the fixture/change example is built correctly, which mirrors the script.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-verdicts.md:36
- Covered by: WS7 (ct-7uit).
- See docs/reviews/2026-10-24-ticket-audit/README.md
