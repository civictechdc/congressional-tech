---
id: ct-o2pr
status: open
deps: []
links: [ct-qg8e, ct-64el]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, site, phase2]
---
# Hearing pages show duplicate transcripts

Events with duplicate transcript entries went from 3,199 to 11,263 in 448651e7, 8,064 of them new; entries went from 20,531 to 32,882. 959c23ee adds one entry per row, HearingDetail.tsx:172 does not dedupe, and no expected entry count was defined. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

The model defines one transcript entry per hearing package with its formats, and a check enforces it. Recheck after the ZIP rule, which may remove the new duplicates.

