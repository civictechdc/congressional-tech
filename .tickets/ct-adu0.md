---
id: ct-adu0
status: in_progress
deps: []
links: []
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Replace whole-corpus pickle staging with resumable typed preparation

Replace CatalogDependencyStorage.adopt whole-corpus SQLite payload staging with bounded typed partitions and reusable completed native work. Preserve source order, identity, aliases, duplicate/null/nested values and existing CatalogRows occurrence splitting. Reuse maintained storage and selection owners.

## Acceptance Criteria

Record before/after wall time, staging bytes and memory on identical fixture including large occurrences. Exact source/document/mapping equivalence. Interrupted continuation reuses completed work and refuses changed inputs. Detect capacity failure before expensive staging; preserve original failed operation.

