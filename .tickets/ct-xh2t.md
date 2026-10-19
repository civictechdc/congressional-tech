---
id: ct-xh2t
status: closed
deps: [ct-yxup]
links: []
created: 2026-10-19T16:11:14Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-8w0g
tags: [download-cleanup]
---
# Give the Congress.gov downloader a transport owner

Move the existing API constant and JSON request wrapper from meeting collection to transport/congress.py. Both collectors use the transport owner; retain existing meetings imports.

## Acceptance Criteria

Five-attempt default, explicit override, key/format precedence, caller parameters and JSON failure behavior remain identical; collector and import tests pass.


## Notes

**2026-10-19T16:15:22Z**

Extracted the unchanged Congress.gov API constant and JSON downloader into transport/congress.py. Both collectors import the transport owner; meetings.API and meetings.get remain available through explicit imports. Offline focused verification: 125 passed in 9.12s, covering both collectors, attempt override, parameter precedence, unchanged caller mapping, JSON failure, XML recovery, HTTP policies and import fences. Implementation remains in progress pending independent review.

**2026-10-19T16:16:48Z**

Independent review approved c3bf67a; downloader function AST matches the original. 125 offline tests passed. Combined integration remains tracked by ct-kpuy.
