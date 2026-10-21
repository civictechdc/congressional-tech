---
id: ct-omnp
status: closed
deps: []
links: []
created: 2026-10-20T17:10:33Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-czsd
tags: [tests, qualification]
---
# Use the maintained catalog bound in CLI test reads

Two CLI integration tests publish a catalog with the maintained 16 MiB declared chunk bound, then their shared table helper asks the reader to admit only 1 MiB. The reader correctly refuses before the tests can check capture/publication behavior. Both failures reproduce on b0ddf871 before writer retirement.

## Acceptance Criteria

Make only the test helper use the maintained catalog writer bound. Preserve the explicit undersized-bound rejection tests and all capture/resume/publication assertions. Do not change production limits or reader guards. Red/green locally, independently review, merge and archive the isolated worktree.


## Notes

**2026-10-20T17:17:49Z**

Implemented in 49b789e1. Independent review approved, grade A: 41 local checks passed, two actual-native checks intentionally excluded; all 39 assertions unchanged. The undersized-read rejection remains tested. Only the test helper now reuses the maintained writer bound; production behavior and limits are unchanged.
