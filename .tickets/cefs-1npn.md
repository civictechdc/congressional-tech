---
id: cefs-1npn
status: closed
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


## Notes

**2026-10-28T05:43:27Z**

Exact supplied 1907-byte old pointer snapshot refuses in the shared reader and canary after one pointer request. Built actual ac866 desktop, phone, stale reload and old-pointer refusal pass; the phone shows clear error and retry with zero documents, zero legacy/data-asset requests and no uncaught page error. Eleven reader units and five tool checks pass. Static CODE review APPROVE 5e481f50^..14f961f9, no findings. No production refusal policy changed; engine owns explicit first switch.
