---
id: ct-y32m
status: in_progress
deps: [ct-rcs8]
links: []
created: 2026-10-20T15:54:57Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency]
---
# Reuse verified retained catalog files during explicit adoption

The 1.09 GB current catalog pair is retained and verified, but read_catalog always downloads it again. Adoption should accept explicit retained files while checking the live selector and original file identities.

## Design

Use the existing snapshot and file validation owners; add a narrow explicit retained-input option with no automatic fallback and no second read authority. Preserve source file custody and close behavior.

## Acceptance Criteria

Exact retained files avoid remote payload reads; changed selector, hash, size or row metadata refuse before native work. Preserve original files on success and failure. Test, independent review and local integration.

