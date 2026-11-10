---
id: ct-a73a
status: open
deps: []
links: [ct-m704]
created: 2026-11-10T05:38:12Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, ocr]
---
# Body-text run: 14 bodies wrongly decided unreadable (7 page_deadline after pauses, 7 memory_limit at 1 GiB)

Found by the OCR throughput investigation 2026-11-10 (.cache/archive-release/investigations/ocr-throughput-20261110/README.md, sections 'Worker restarts' and the page-deadline section, with the body hashes). (1) page_deadline (parsers/body_text.py) uses ITIMER_REAL, a wall-clock timer that keeps running while a job is stopped; the full run's driver paused batches with SIGSTOP for release work, so after any pause over 60 s every in-flight page raised PageDeadline on resume, and a body hit twice was recorded unreadable: page_deadline. Seven bodies in chunk-0014. The driver no longer pauses (it ends the open batch instead, since 05:36Z), but the timer is still exposed to a laptop sleep or a debugger stop, and the 1,800 s document deadline (time.monotonic) the same way. (2) The supervisor kills a worker at WORKER_MEMORY_BYTES = 1 GiB; a second kill records unreadable: memory_limit. pdf_text over 32 test documents peaked at 1,060 MB, so ordinary large PDFs cross it: seven bodies so far, about 14 kills an hour. The limit is tied to workers x 1 GiB inside the engine's 14 GiB limit.

## Acceptance Criteria

The 7 page_deadline decisions are superseded and the bodies read; the 7 memory_limit bodies are re-read with a 2 GiB worker limit and each is either read or kept unreadable with its measured peak; the page deadline counts running time, not wall time across a stop, with a test; the body-text pool has its own memory budget so a 2 GiB per-worker limit does not shrink the worker count.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10: the cause of the 7 page_deadline decisions is removed for future batches: the driver no longer pauses a batch (SIGSTOP let the page timer expire); it kills the open batch and reruns it. The 14 wrong decisions themselves are not yet superseded, and the 2 GiB worker limit is not yet set.
