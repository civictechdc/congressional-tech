---
id: ct-zhta
status: closed
deps: []
links: [ct-r4rd]
created: 2026-11-02T04:01:45Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [model, meetings, phase2]
---
# Closed Hearing titles followed by an open session publish closed

review-c-explorer: 7 Closed Hearing titles with "followed by an open" publish closed because the rule is one-directional.

## Acceptance Criteria

Those are partly_closed, with a test.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Access fix changes exactly the 7 meetings. impl-f.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): 7 rows changed, all supported by the raw check; the one-way rule dates from 2351caf4.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
