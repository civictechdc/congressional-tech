---
id: cefs-1npn
status: in_progress
deps: []
links: []
created: 2026-10-28T05:36:37Z
type: task
priority: 1
assignee: site
---
# Refuse the old viewer pointer in the new archive consumers

Lead decision 20261028T053210Z: the current public pointer still has the old filename-viewer shape. Bind exact local refusal in the reader, canary and built browser without reading old catalog, recovery or release folders.

## Acceptance Criteria

The actual supplied old pointer produces a clear refusal, no uncaught browser error and no fallback asset read. Focused npm checks and the maintained built browser contract pass; engine owns the first conditional flip.

