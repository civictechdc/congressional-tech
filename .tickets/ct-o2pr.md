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


## Notes

**2026-11-02T04:01:45Z**

No code yet; recheck after a rebuild, since the ZIP rule may remove the new duplicates. The one-per-package rule and check do not exist.

**2026-11-02T10:36:11Z**

2026-11-02: one confirmed duplicate source. Cloudflare email obfuscation makes the ZIP member HTML (b14d49d9) and the direct HTML (c7768761) of CHRG-119hhrg64404 fingerprint differently though they are the same transcript. See ct-64el.
