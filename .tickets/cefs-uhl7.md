---
id: cefs-uhl7
status: closed
deps: []
links: []
created: 2026-10-28T16:12:54Z
type: task
priority: 2
assignee: site
---
# Prepare post-flip site pointer bridge removal

Post-deploy deletion branch only: remove the Node canary first-flip old-viewer admission while preserving current reader contracts, negative rejection tests and public pages.

## Acceptance Criteria

Remaining archive tools/tests and Astro build pass; old pointer rejects with or without a pinned candidate; no merge before lead deploy confirmation.


## Notes

**2026-10-28T16:18:55Z**

Prepared on the strip branch only. Nine surviving tool tests pass; Astro build retains all30 pages with byte-identical HTML. Unsupported pointers reject before assets with or without a pinned candidate. Merge remains gated on lead deployment confirmation.
