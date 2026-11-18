---
id: ct-zohj
status: open
deps: []
links: []
created: 2026-11-18T17:57:22Z
type: task
priority: 2
assignee: mikewolfd
tags: [recovery, capture]
---
# Start recovery when a fetched file fails to open, and stop refetching identical bytes

Found 2026-11-18 on ct-z4w5. The 49 damaged PDFs were served with HTTP 200, so the ladder treated each fetch as a success and never started archive discovery; 47 refetches then returned byte-identical damaged files. The architecture table (docs/recovery/holistic-recovery-architecture-20261031.md) now has the row '200 with a body that fails qualification: preserve it, go to archive discovery, do not fetch the same address again unless its validators change', marked not yet enforced (pull request 205).

What enforcing it takes (read from the code by the agent that built pull request 205; verify before relying on line numbers):
- capture_scheduler.py (about lines 935-954) fetches, writes the receipt and branches only on the storage outcome; 'stored' / 'unchanged' (body_store.py:103) means bytes were stored, not that they read.
- Rescheduling reads capture_disposition from URL state (capture_scheduler.py about 412-413 and 575-577); URL state sets it only from accepted recoveries and scope exclusions (archive_url_state.py about 181-187). No qualification fact exists there.
- The fetcher sends no conditional headers; receipts already keep ETag, Last-Modified and Content-Length (receipt_writer.py 22 and 117).
So three pieces: a qualification fact per body (a parse and render per PDF at capture or model time: measure that cost first), URL state marking the address done for refetch, and a due-time rule that refetches only when a validator changes.

Owner decisions needed: where the readability check runs and what it may cost per night; which validator changes count as 'the publisher replaced the file'.

## Acceptance Criteria

A body that fails qualification is routed to discovery without a person noticing it; an address that returned identical bytes is not fetched again until a validator changes; the per-night cost is measured and recorded.

