---
id: ct-c6b0
status: open
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
