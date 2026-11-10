---
id: ct-u9y4
status: in_progress
deps: []
links: []
created: 2026-11-10T05:08:06Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, recoveries, identity]
---
# Recovered documents with the same file name are fused: 215 documents hold several different recovered bodies and show one

Found 2026-11-10 by the all-live-link-keys check on release candidate 619db5f9 (.cache/archive-release/release-20261110/causes-2/orchestrator-checks/all-live-link-keys.md). Link key cae8e4ea34ec603a, 'Bowman Testimony.pdf': the live release shows Terry Bowman's testimony to House Oversight of 2012-02-08 (15 pages, 639,987 bytes, oversightdemocrats.house.gov); the candidate shows his testimony to the Education and Workforce HELP subcommittee of 2018-04-26 (12 pages, 342,509 bytes, democrats-edworkforce.house.gov). Two different documents are one row because both are recovered under one file name; which is shown flipped when one was fetched live on 2026-11-08. The candidate's recoveries.parquet has 215 documents with two or more different recovered bodies, 187 from different hosts (row 1472: augustine.pdf from a 2004 and a 2007 Science hearing). How many are truly different documents is unmeasured. An existing class on the live release, not caused by ct-h3jb or ct-f7hp; raw holds every body.

## Acceptance Criteria

Every multi-body recovery document is either shown to be one document (same text) or split, with counts. Bowman 2012 and 2018 are two rows. A release gate or model invariant flags a recovery document whose bodies differ in text.


## Notes

**2026-11-10T13:16:36Z**

Owner decision 2026-11-10: correct the records. Mark the wrong acceptances in the recovery records and re-record each file under its own address (option 1 with re-recording), so each hidden file becomes its own document.

**2026-11-10T13:27:30Z**

2026-11-10 status: the model rule (a recovered copy moves its link only when it is the copy the link shows) is on claude/ct-next-release (4bd50c6d..f8192a6a) and separates 18 of the 56 unrelated fusions. For the remaining 38 the owner chose record corrections; a builder is preparing them and proving them on a local copy in wt/ct-u9y4-records (report: .cache/archive-release/investigations/recovery-records-20261110/README.md). No raw write happens until the orchestrator has read that report. Left: the correction write, full model build, review, release.
