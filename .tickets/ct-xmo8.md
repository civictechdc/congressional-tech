---
id: ct-xmo8
status: open
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:35:49Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Keep browser retries on the accepted catalog

An ordinary reader starts with no explicit snapshot; after worker failure it can resolve a newer mutable pointer while the page retains old metadata.

## Acceptance Criteria

Pin the first accepted catalog for later requests and worker recreation. Preserve explicit selections and cancellation. Local tests cover pointer advance, failure, retry and conflicting responses.
