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

**2026-11-11T14:41:00Z**

validated 2026-11-11, left open: only the cause of the 7 page_deadline decisions for new batches is gone (the driver no longer pauses). Checked on origin/main: parsers/body_text.py:174 still uses signal.ITIMER_REAL (wall clock), lake/body_text.py:54 still takes WORKER_MEMORY_BYTES from readings (1 GiB); the 14 wrong decisions are not superseded.

**2026-11-12T04:30:00Z**

Wave 6 prep landed on `claude/ct-wave-6-bodytext-prep` (left open solely for the post-OCR `--apply` pass once `bt_full_driver.py` drains):
- `parsers/body_text.py:page_deadline` switched from wall-clock `signal.ITIMER_REAL` (`SIGALRM`) to process user-CPU `signal.ITIMER_VIRTUAL` (`SIGVTALRM`), disarming via `SIG_IGN` before clearing the timer and subtracting elapsed `ru_utime` when restoring a nested outer virtual timer (while `ParserWorker`'s 1,800s `time.monotonic()` deadline bounds wall/XPC stalls); tested across CPU burn, nested timers, wall-clock sleep, and `SIGSTOP`+`SIGCONT`.
- `lake/body_text.py:WORKER_MEMORY_BYTES` raised to `2 << 30` (`2 GiB`) with dedicated pool budget `PARSER_MEMORY_BYTES = 32 << 30` (`32 GiB`, plus `--parser-memory-bytes` / `parser_memory_bytes` in `cli/body_text.py`) so `engine.limits` (`14 GiB`) does not cap workers to 7; `lake/body_text.py` (`_MeasuredWorker` + `stage()` `body_outcomes`) records per-body `peak_rss_bytes` and `error`; `pdf_text` (`2980a4db...`), `html_text` (`e1928f25...`), `xml_text` (`ed9eb0e2...`), and `lake/versions.py` (`_REVIEWED_PRODUCER_VERSIONS`) are 100% unchanged.
- Unified `reason <> 'withdrawn'` (`supersedes=<id>` required) across plumbing and model active-unreadable consumers via `retention/provenance.py` (`active_unreadable_where`, `active_unreadable_rows`): `lake/body_text.py`, `lake/readings.py`, `lake/daily.py`, `viewer_publication/archive_model.py` (`profile-completeness.sql` & `document-page-metadata.sql`), `viewer_publication/body_text_export.py`, `viewer_publication/archive_house_xml_dispositions.py`, and `viewer_publication/archive_house_xml_transition.py`, without touching any byte-hashed record producer.
- Read-only inventory (`.cache/archive-release/investigations/wave6-bodytext-prep-20261112/ct_a73a_unreadable_inventory.json`): 16 JSONL files in `body-text-slice-20261109/unreadable-store/provenance/unreadable/` hold **31 active `pdf_text` records**: the **7 `page_deadline`** bodies from chunk-0014 (`20261109T190000+0000-e9771666...jsonl`) plus **24 `memory_limit`** bodies accumulated at 1 GiB.
- Concise 159-line post-OCR retry script `scripts/retry_unreadable_body_text.py` (synced to `.cache/archive-release/investigations/wave6-bodytext-prep-20261112/retry_unreadable_ct_a73a.py`) verified read-only with `--dry-run` (`0 -> 31` targeted work items, `72` capture rows; refuses `--apply` while `bt_full_driver.py`, `congress_api.cli.body_text`, or `nightly_publish.py` is running; idempotently imports withdrawals only for not-yet-superseded decisions and reports per-body `peak_rss_bytes` in `apply-summary.json`). Run `--apply` under `archive_watchdog.py --rss-gb 20` once `bt_full_driver.py` finishes draining.
