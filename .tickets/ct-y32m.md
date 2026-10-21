---
id: ct-y32m
status: closed
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


## Notes

**2026-10-20T16:04:50Z**

Reviewed and integrated as 514243eb with ct-9vtu custody guards. Explicit retained inputs require exact live selector, hash, size and row checks; stale/corrupt files refuse with no remote fallback. Independent 42 tests and combined 62 tests passed; completed CLI retries preserve exact values and perform no new writes/imports. The current retained pair totals 1,087,995,353 bytes, which this path avoids redownloading; this is a byte-count saving, not a measured latency claim. Review: review-merge/retained-input-review.md. Grade A-. Production acceptance remains ct-2ukk.
