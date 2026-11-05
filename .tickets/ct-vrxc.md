---
id: ct-vrxc
status: closed
deps: []
links: [ct-vq2a]
created: 2026-11-05T02:36:33Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, parser]
---
# Filename date lost when a title contains 'Act of YYYY' before the real date (EPS Improvement Act of 2016 1-12-16)

saved-copy-identity stops 'Act of <year>' from dating documents, which loses the real trailing date on 'FP Opening Statement--EPS Improvement Act of 2016 1-12-16.pdf' (was 2016-01-12, now undated). A correct fix needs the filename reader to skip the act-title token and keep reading, which bumps the house_naming parser version (byte-hashed) and needs a filename_readings backfill.

## Acceptance Criteria

The reader dates that filename 2016-01-12 and still refuses 'Act of 2019_6-23-20' style misreads; batch with the next filename-reader change.


## Notes

**2026-11-05T13:09:52Z**

Implemented and selectively backfilled in the qualified 7f9ebddd source. The EPS filename produces date token 1-12-16 and 2016-01-12 while Act-title misreads remain rejected. Recomputed 295 of 1,403,275 filename readings, reused 1,402,980 with exact value proof, and reconciled the related House XML parser pin without replaying unaffected XML. Imported tables and producer anchors passed native parity and all six model suites. Final candidate e145d24c389e preserves 2016-01-12 through actual MCP/browser checks. Publication remains pending the owner review explicitly reserved in the Cursor session. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/{filename-date-repair,candidate-streaming-repair,final-acceptance}/.

**2026-11-05T15:45:07Z**

The actual published EPS statement retains 2016-01-12. Act-title rejection, selective filename recomputation and the related House XML version transition are complete and producer-verified. Published and independently verified in e145d24c389e (2026-11-05), replacing e4538f00. Qualified source 7f9ebddd; publication source 0d517fd5. All three offline shards passed (11,497 tests), full native/storage lanes passed, all six data suites passed, and all 26 public assets match the approved bytes. Live checks passed 180 MCP assertions and 57 deployed-browser assertions. Release note: docs/releases/2026-11-05-e145d24c389e.md. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/.
