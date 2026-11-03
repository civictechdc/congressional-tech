---
id: ct-n2cy
status: closed
deps: []
links: [ct-sh4j, ct-qg8e, ct-yf1c, cef-96wc, ct-tk10, ct-d0o0]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, phase2]
---
# publish_v21 published 72 sources rows with NULL url

72 source_ids have a real capture plus a stored row with NULL context_url. document-addresses.sql keeps every context of a source whose member is real, without filtering the context row, so the NULL row becomes a published address. Traced to 068f2a40, exposed by bc0a146c. 12 documents have only this NULL address. It crashes compare_committee_meetings_archive.py; the registry does not declare url required, so native checks did not refuse it. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

0 NULL sources.url, and a native check at write time that refuses one.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge, stay open until a full run shows 0 NULL URLs. The 12 NULL-only rows are raw YouTube API responses, now non-document by role; 345 JSON rows read by the implementer.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
