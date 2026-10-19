---
id: ct-u7gg
status: in_progress
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:35:49Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Carry existing file and catalog checks through local publication

R2 derived-file reads discard VerifiedFile custody when adding version. publish_local_result drops CatalogBuildResult validation. Both force another integrity pass.

## Acceptance Criteria

Preserve issued proofs only within their existing process/file binding. Count tests show no redundant SHA/reference pass on the actual route; plain restored data and changed files still require checks or fail.

## Notes

**2026-10-19T16:43:11Z**

Implemented exact issued R2 file-proof preservation while retaining version/mapping metadata, plus CatalogBuildResult validation forwarding on direct local publication. Focused real handoff fixtures show 0 redundant SHA bytes with issued proof versus 1052 bytes for restored facts; changed issued custody refuses before upload and changed restored facts hash then refuse. Direct local build reference calls fall from 2 to 1. 132 focused tests pass; primary output/package-overlap-rescore-20261019/storage-proof-{red,green}.log retained. Awaiting independent review before closure.
