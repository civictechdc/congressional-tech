---
id: ct-v5kb
status: in_progress
deps: [ct-l5q1]
links: []
created: 2026-10-20T02:20:21Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Publish reusable catalog partitions and migrate readers

catalog_publication.py:134 publishes two complete new files for each result. The representation prevents cheap delivery even when computation is incremental.

## Design

Use the maintained versioned-table mechanism qualified in ct-l5q1 to select changed partitions and retain unchanged ones. Preserve the two logical tables and their coherent selection; do not preserve monolithic files as an internal requirement. Keep the existing conditional selector and stale-writer protections. Work against fixture changes independently of catalog computation.

## Acceptance Criteria

- Baseline current writer and reader behavior before edits: nested schemas, ordering, counts, references, hashes and failure cases.
- Publish one changed partition without reading, rehashing or uploading unrelated payloads. Bind reused proofs to exact immutable versions and validator requirements; stale proofs cannot authorize selection.
- Migrate catalog_publication, CLI/local readers, recovery custody/validation and viewer preparation. Inventory dynamic callers as well as imports. No active consumer forces full export on routine updates.
- Prove coherent selection, competing writers, missing partitions and lost acknowledgments. Preserve old selected snapshots and reject partial or mixed generations.
- Report rewritten/reused bytes and metadata costs. Remove superseded internal readers after migration; any full export is an explicit user operation, not an update dependency.
