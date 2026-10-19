---
id: ct-xh2t
status: open
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

