---
id: ct-rvma
status: closed
deps: []
links: [ct-vq2a, ct-cxc5]
created: 2026-11-05T02:36:33Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model]
---
# Printed hearing dated by a later re-posting instead of its meeting (CHRG-117hhrg49353)

Under saved-copy-identity, CHRG-117hhrg49353 takes 2023-06-07 from its only dated copy, a re-posting at a later hearing; it was dated by its 2022-06-23 meeting.

## Acceptance Criteria

A printed hearing (CHRG package) prefers its own meeting date over a filename date from a later re-posting; fixture.


## Notes

**2026-11-05T13:09:52Z**

Implemented at qualified source 7f9ebddd. Exact package/held-meeting corroboration restores CHRG-117hhrg49353 to 2022-06-23 instead of the 2023-06-07 reposting filename. Existing undated hearings remain undated; multiday and CHRG-119hhrg60403 controls retain their actual hearing dates. Native corpus, independent cover/false-date controls, and MCP/browser checks pass for final candidate e145d24c389e. Three distinct baseline cover disagreements are recorded in a linked follow-up. Publication remains pending the previously reserved owner cause review. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/{document-identity-repair,candidate-streaming-repair,final-acceptance}/.

**2026-11-05T15:45:07Z**

The actual published CHRG-117hhrg49353 date is 2022-06-23. Reposting, multiday and CHRG-119hhrg60403 controls passed. Three separate preexisting cover disagreements remain in ct-cxc5. Published and independently verified in e145d24c389e (2026-11-05), replacing e4538f00. Qualified source 7f9ebddd; publication source 0d517fd5. All three offline shards passed (11,497 tests), full native/storage lanes passed, all six data suites passed, and all 26 public assets match the approved bytes. Live checks passed 180 MCP assertions and 57 deployed-browser assertions. Release note: docs/releases/2026-11-05-e145d24c389e.md. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/.
