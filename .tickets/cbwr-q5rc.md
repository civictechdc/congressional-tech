---
id: cbwr-q5rc
status: closed
deps: []
links: []
created: 2026-10-28T02:31:49Z
type: bug
priority: 0
assignee: mikewolfd
---
# Complete B15 preservation for both pipeline snapshot workflows

## Acceptance Criteria

Both workflows provide uv and raw credentials before saving; local setup/body/receipt failures prevent pushes; SDK local fake tests pass; owner release commands and 35-snapshot counts are current


## Notes

**2026-10-28T02:57:43Z**

Both workflows now provide setup and R2 environment; the real YAML commands pass failure-before-push tests against local Git/raw fakes. 150 focused checks and 26 real SDK local HTTP loopback tests pass. Owner release and raw readback commands are complete. Semi-formal review APPROVE, no open concern.
