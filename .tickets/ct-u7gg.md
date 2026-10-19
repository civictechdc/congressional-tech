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

**2026-10-19T16:43:56Z**

Independent review requested the exact R2 read-to-retain_verified_file boundary in addition to history upload. Added four actual read/retention cases: issued proof retains 26 bytes with zero additional SHA work; restored facts hash all 26 bytes; changed issued custody refuses before retention; changed restored facts hash then checksum-refuse. Version, exact retained bytes and same-inode retention are asserted. Final combined focused suite: 166 passed. Final log: primary output/package-overlap-rescore-20261019/storage-final-green.log. Ticket remains in_progress pending review.

**2026-10-19T16:44:45Z**

Retain-test correction: the first added run had 165 passes and one assertion failure because plain restored-facts retention has always recomputed hash/size without version enrichment. The fixture now asserts the unchanged plain-facts semantics and issued-proof metadata separately. That initial failure is retained in storage-retain-first.log; final actual run passed all 166 tests in 4.11 seconds. No runtime behavior was changed for this fixture correction.
