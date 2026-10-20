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

## Notes

**2026-10-20T03:15:53Z**

Reviewed exact-partition reader merged as 4f056c2; 9c1b965 removes quadratic partition membership checks while retaining selector order. Twelve independent core tests and two ordering cases passed. Coherent writer selection, durable semantic proof and consumer migration remain in progress; this is not a production switch. Review: output/incremental-updates-20261019/publication/reader-core-review.md.

**2026-10-20T03:35:36Z**

Independent review found that per-document native datasets would multiply fixed provider work across the archive. Coalesce physical storage across document components before runtime integration. Also separate current-proof admission from historical snapshot reads; old selected versions must remain readable after validator upgrades. Five focused checks passed, but this checkpoint is not approved for adoption. Review: output/incremental-updates-20261019/publication/component-proof-review.md.

**2026-10-20T04:07:17Z**

Shared physical batches, paged component proofs, historical readers and one conditional native catalog selector are reviewed and merged locally. 47 preparation/proof checks and 25 selector/routing/publication checks passed. In the 130-document stub comparison, native Run calls fell from 260 to 2 and metadata PUTs from 130 to 6; this is not production latency. Maintained callers and viewer migration remain required.

**2026-10-20T04:49:46Z**

Stable viewer builder and retained withdrawal safeguards integrated; joint builder, review, cursor and lookup tests: 42 passed. Recovery preparation: 34 baseline checks and 8 review-fix checks passed. Browser/uploader migration and native operational phase connection remain open; existing published viewer is unchanged.

**2026-10-20T05:34:22Z**

Shared native preparation now serves cloud and local recovery publication; recovery-only mode preserves exact prior manifest bytes. Native runtime input custody and low-compression policy are integrated locally. Hosted native distribution is still absent; no deployment/adoption claimed.

**2026-10-20T07:20:03Z**

Renderer interruption fixes and maintained caller upgrade/resume are reviewed and merged locally in0fc67e5f. Atomic files keep partials outside accepted assets; worker loss around immutable linking is covered. Combined suite118 passed. Hosted runtime installation and production adoption remain separate pending work.
