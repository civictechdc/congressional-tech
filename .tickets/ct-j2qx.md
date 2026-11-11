---
id: ct-j2qx
status: open
deps: []
links: []
created: 2026-11-11T19:07:43Z
type: bug
priority: 2
assignee: mikewolfd
---
# Watchdog FIFO admission lets one big queued job starve small ones

2026-11-11 18:31-19:07Z: OCR chunk-0089 (expect 12 GiB + headroom 6) queued first while about 14 GiB was free, so it could not start; congress-1's 1 GiB MODS read probe queued behind it and was refused for 36 min because admissible() subtracts the head waiter's expect_gb (scripts/archive_watchdog.py:106-114). Neither job ran until OCR was paused. Fix at the root: a waiter whose own need is met should not be blocked by a head waiter that cannot fit now (e.g. reserve the head only once it could fit, or let small jobs pass), keeping the no-overcommit guarantee; add a test with one big unfittable head and one small fittable job.

