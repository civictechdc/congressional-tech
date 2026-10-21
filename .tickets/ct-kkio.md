---
id: ct-kkio
status: closed
deps: []
links: []
created: 2026-10-20T16:53:04Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-czsd
tags: [publication, tests]
---
# Exercise the current hosted runtime guard in workflow tests

The workflow guard test runs setup-native-runtime.py from an empty temporary directory and expects the removed inline guard message. It fails before testing runtime admission, so the broader local suite cannot verify the current no-credentials refusal.

## Acceptance Criteria

Run the real current guard from a minimal isolated checkout or resolved script path, with secret variables removed. Assert its current missing-configuration refusal and no runtime installation/provider operation. Preserve resume/no-op skip assertions. Test locally, independently review, merge and clean up.


## Notes

**2026-10-20T16:58:19Z**

The test now executes the current setup helper from a minimal checkout with an allowlisted environment. It verifies the exact missing-configuration refusal and absence of generated files. Author and independent reviewer passed 47 focused checks plus an ambient-input sentinel; root passed 145 combined publication/runtime checks after integrating PR142. Independent verdict APPROVE, grade A. Evidence: output/incremental-updates-20261019/review-merge/runtime-guard-test/review.md. Production logic and the running import remain unchanged.
