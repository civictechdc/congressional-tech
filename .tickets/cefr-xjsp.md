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

**2026-10-27T19:29:00Z**

Confirmed F2 CODE/ARCH concerns reproduced cd94e9a8. Fixed full single-PUT allowance4ac9f494 (source314→317lines), unsafe discovery refusal a582b05f (317→341), and all-reviewed native cutoff dispositions in current follow-on (341→397). 104 focused checks pass4.28s on6fc6a94. Shared E url_key and D2 worker still pending; exact-alias regression contracts being added. Bounded replans cost O((D+2)*N) input passes, defaultD8→10passes, plus per-capture fetch/write work.
