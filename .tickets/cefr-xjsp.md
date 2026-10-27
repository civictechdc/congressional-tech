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

**2026-10-27T19:09:26Z**

Implementation binds native public-release queue planning, bounded weekly seeds, immediate bounded discovery replans, B2/B3 writers and exact raw receipts. Focused scheduler/fetcher/receipt/store runner: 99 passed in3.23s (focused5.log); first broad import-fence run117pass/1new lake-fence issue, reported to D1 owner. No network/store run. Remaining: root independent CODE/ARCH review, first real E-release scope/due/cutoff-budget qualification and owner first live run.
