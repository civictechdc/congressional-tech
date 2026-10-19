---
id: ct-u9jl
status: closed
deps: []
links: []
created: 2026-10-19T15:46:01Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-snh8
tags: [package-cleanup, behavior-preservation]
---
# Read YouTube caches through one shared decoder

Inventory, video matching and Explorer export each decode YouTube cache tables. Use one standard-library-only decoder in congress_shared.youtube_cache; consumers retain file access, provenance and matching policy. This preserves the existing package dependency boundaries.

## Acceptance Criteria

Preserve cache rows, order, channel identity, missing-file behavior and matching/export outputs. No input writes or downloads. Regression fixtures cover multiple tables, empty caches, metadata and malformed inputs. Document the decoder and keep dependencies explicit.


## Notes

**2026-10-19T15:46:23Z**

Implementation authorized in an isolated worktree. Preserve source data and production workflows. Ticket closes after focused checks and independent review; parent tracks merge completion.

**2026-10-19T15:48:14Z**

Source inspection found an existing congress-api boundary that forbids dependencies on youtube-api and its collector dependencies. Keep that boundary: place the standard-library-only TinyDB format decoder in congress_shared.youtube_cache, already declared by both packages, and use it from the three existing readers. Keep file access, original byte retention, lazy failure behavior, table/row ordering, matching and publication policies in their current callers. No dependency or lockfile change is needed.

**2026-10-19T15:50:58Z**

Implemented one standard-library-only decoder in congress_shared.youtube_cache: videos() yields literal table handle plus unchanged video row; channels() yields unchanged metadata. Inventory, GPO matching and Explorer use it while keeping local file I/O and policy. Declared congress-shared directly for Explorer (already in its installed dependency closure); uv.lock changes only that direct edge. Verification: 169 focused tests passed, plus 7 subtests (cache regression, CLI, inventory, exporter, YouTube adapter, import/dependency boundaries, interpretation and fetch fidelity). uv lock --check --offline and git diff --check passed. A bounded socket-blocked comparison against original b191fc8 source produced identical inventory rows, GPO candidates, and complete JSON publication files for unlimited and limit=1 exports, with deterministic test IDs and unchanged input bytes. No source downloads, retained data edits, corpus rebuilds or production actions. Keep in_progress pending independent review and parent merge.

**2026-10-19T15:55:09Z**

Independent config-lane reviewer approved implementation f8ae6b6. Twenty original/current inventory and GPO comparisons preserved values, ordering, failure timing and bytes. Export provenance and the unchanged package dependency closure checked. 169 tests plus seven subtests passed. Parent ct-snh8 tracks CI, merge and cleanup.
