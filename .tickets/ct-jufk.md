---
id: ct-jufk
status: closed
deps: []
links: [ct-r6xw]
created: 2026-10-20T16:47:28Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [publication, qualification]
---
# Load publication identity helper in a fresh CLI process

Publisher run 39459155814 at b0ddf871 passed validation but failed during preparation: `release_source_files` imports `viewer_release_identity` without its scripts directory on the fresh process import path. The test process had masked this dependency. No publication writes occurred.

## Acceptance Criteria

Reproduce through a fresh subprocess with only the maintained package paths. Resolve the existing helper through the supported CLI bootstrap/import route; preserve the fingerprint algorithm, source coverage and runtime behavior. The implementation digest must still change when its source changes. Test locally, independently review, merge and archive the isolated worktree. Do not retry or dispatch workflows or touch the running catalog import.


## Notes

**2026-10-20T16:55:21Z**

One-line CLI bootstrap fix committed as 2d36311b. The fresh-process regression reproduced the hosted failure, then passed with the shared identity helper and native-storage refusal intact. Author and independent reviewer each passed 99 focused tests. Independent verdict APPROVE, grade A-. The unrelated stale guard fixture is tracked by ct-kkio. Evidence: output/incremental-updates-20261019/review-merge/publisher-release-import/review.md. No workflow retry, publication write or active import change.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch czsd).
- Grades: proposal 91 → 91, work 85 → 85.
- Problem: `f5e8fe1b` (Oct 24) added a shim (`viewer_publication/release_identity.py:12-16`) that puts an empty module named `viewer_release_identity` in `sys.modules`.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-verdicts.md:52
- Covered by: WS6 (ct-qqk2) and WS10 (ct-r6xw), which delete `release_identity.py` and its `sys.modules` stub.
- See docs/reviews/2026-10-24-ticket-audit/README.md
