---
id: ct-u7gg
status: open
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
