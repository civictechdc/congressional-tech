---
id: cefr-xjsp
status: in_progress
deps: []
links: []
created: 2026-10-27T18:55:33Z
type: task
priority: 2
assignee: raw
---
# F2: schedule bounded capture from the live release

Run2 owner reassignment. New target path beside live raw_sync; site owns workflow wiring.

## Acceptance Criteria

Native due planning preserves queue/cutoff/time order and seed schedules; target capture uses Fetcher/ReceiptWriter/BodyStore with request-byte-spool bounds and no raw index/replay; local fixture contracts pass; first live run has exact owner command.


## Notes

**2026-10-27T18:59:14Z**

Contract suite authored first: six behavioral cases fail only because capture_scheduler does not exist (project runner, contracts-red.log). Implementation follows in a separate commit; no existing assertion changed.
