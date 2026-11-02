---
id: ct-xls0
status: open
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
