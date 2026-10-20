---
id: ct-i7j2
status: closed
deps: []
links: []
created: 2026-10-20T16:29:12Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [publication, qualification]
---
# Align publisher compression test with approved level 3 default

Publisher run 39454496332 failed before publication: one stale test expects Zstandard level 9 although the approved default is level 3. The other 293 checks passed. Preserve runtime behavior and existing data.

## Acceptance Criteria

Reproduce the stale expectation locally; update the test and its name to the approved level 3 policy; pass relevant local publication tests and independent review. Preserve the failed run evidence. Do not retry or dispatch workflows.


## Notes

**2026-10-20T16:32:34Z**

Reproduced the exact stale level-9 assertion locally. Changed only the test name and expected default to approved level 3. All 294 tests from the failed publisher validation step pass locally in 28.14s with imports pinned to the isolated checkout. Failed-run ZIP and logs retained; no workflow retry. Independent review pending.

**2026-10-20T16:36:59Z**

Independent review approved b1f48e8e with no findings; grade A.294 local publisher checks pass. Runtime behavior and source data unchanged; original failed hosted run retained without retry.
