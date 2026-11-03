---
id: ct-xls0
status: closed
deps: []
links: [ct-egg6]
created: 2026-11-02T03:17:51Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [senate, acquisition, phase2]
---
# Senate page outages can still exit 0

Final review of 180a49b1. In acquisition/senate.py, a repeat run over never-fetched pages (already error) exits 0 with empty CSVs, and one answer followed by 10 failures in a row stops the host and exits 0.

## Acceptance Criteria

Both cases raise a host error; Budget's known 403s do not trip it; tests cover both.


## Notes

**2026-11-02T14:46:34Z**

2026-11-02 (lead): red-e2: a Senate outage can still exit 0: senate.py:420-423 counts every failure as known if any page answered (since a1cce1e5). Fix: record per failure whether an HTTP status came back.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
