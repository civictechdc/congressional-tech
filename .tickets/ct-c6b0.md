---
id: ct-c6b0
status: closed
deps: []
links: [ct-sh4j, ct-qg8e, ct-bxqa]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [captures, phase2]
---
# HTTP 202 firewall responses count as good fetches

23 capture rows have raw outcome http_error at HTTP 202, all firewall (WAF) responses, but are stored and pass good_fetches, which accepts 200-299. Traced to 91254080; four other 2xx tests share the pattern of treating a status as proof of a document. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

The owner decides whether 202 is good; captures and good_fetches follow, with a fixture. The other 2xx tests are checked.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c (3bf52b65); 15 HTTP 202 rows flip from stored. Review: merge, stay open. receipt_writer.py:44 still writes 202 as stored, and removing the archive_url_state.py:28 exclusion fails no test, so add one. Owner ruling on 202 still to record; main treated firewall 202s as not good under the batched fix.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: an HTTP 202 is never a good fetch. Treat it as a failed attempt, keep the receipt, retry on schedule. Fix receipt_writer.py:44 and add the test that fails if the archive_url_state.py:28 exclusion is removed.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Writer fix plus a url_state test that fails if the 202 exclusion is removed; part of the single document rule (ct-bxqa). impl-e1.

**2026-11-03T22:53:34Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
