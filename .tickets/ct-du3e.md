---
id: ct-du3e
status: open
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:38:43Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Keep proposed catalog selectors distinct until verified commit

The local recovery Store saves candidate selector bytes under the selected source path before conditional upload succeeds. A refusal leaves misleading local evidence.

## Acceptance Criteria

Retain a separately named proposal before the write. Preserve prior selected bytes on refusal or uncertainty, and install the new selected receipt only after verified success. Keep original conditions and no automatic retry.
