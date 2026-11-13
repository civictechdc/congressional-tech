---
id: ct-a73a
status: open
deps: []
links: [ct-m704, ct-kfsd, ct-n3ik, ct-hz8y, ct-yy07, ct-t4p3, ct-55qo, ct-aitp]
created: 2026-11-10T05:38:12Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, ocr]
---
# Reconcile resource-failure recovery and measure memory per request

The original defect affected seven paused page deadlines and seven 1 GiB memory-limit decisions. The source fixes have landed: page deadlines use user CPU time and the producer has a separate worker budget. Data acceptance remains open until those original identities are reconciled. The broader recovery is paused after batch 205: 2,422/2,632 committed outcomes (1,316 completed, 1,083 errors, 23 unreadable), with 210 remaining. Do not resume it as part of code work.

## Design

Retain the original cohort and all superseded decisions. ct-55qo owns qualified selection and ct-aitp owns page reuse. The audit found _child_peak_rss_bytes uses process-lifetime ru_maxrss in reused workers: resetting the supervisor sample does not reset that peak. Measure request-scoped memory before ranking individual bodies or raising admission limits; preserve old observations as lifetime measurements. Keep extraction errors separate from resource failures and unreadable decisions.

## Acceptance Criteria

1. Reconcile every original deadline/memory identity to a qualified completed reading or explicit measured unresolved outcome; supersede decisions with provenance only where justified.
2. Preserve the running-time deadline and independent pool-budget regression checks.
3. Request memory measurements are not contaminated by an earlier large request in the same worker; report measurement limitations and worker policy.
4. After the user resumes OCR, finish only the explicit remaining recovery inventory under resource supervision, using ct-aitp checkpoints and ct-55qo selection. A source fix alone does not close this ticket.

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

**2026-11-13T15:00:26Z**

2026-11-13: The full body-text run (body-text-full-20261110, PID 55948, resumed 2026-11-12 21:32Z after the publish yield) finished 2026-11-13T07:44Z at chunk-0173 with status pending: the work list is exhausted except 411 bodies blocked on missing copy metadata. The 2026-11-13 OCR recovery (codex/ocr-recovery-20261113 @ 56421715, .cache/archive-release/ocr-recovery-20261113, separate recovery catalogs) is retrying all 2,632 leftover bodies; at 14:37Z 2,164 had committed outcomes (1,058 completed, 1,083 parser errors, 23 unreadable) and all 411 missing-pin bodies completed. For this ticket's bodies the recovery so far gives memory_limit 56 completed and 3 unreadable, page_deadline 6 completed and 1 error (progress.json by_previous). Close once the recovery's follow-up writes final-summary.json and its outcomes are published.

**2026-11-13T17:46:16Z**

2026-11-13 restart: checkpoint integrity passed for 2,356 outcomes, 2,333 readings and 1,250 texts, preserving the original catalog. At 17:38Z committed outcomes were 1,250 completed / 1,083 errors / 23 unreadable, with 276 targets remaining and batch 198 active. Detached supervisor resumed the frozen 56421715 extraction policy at 17:28:54Z; it schedules final integrity verification and serial 6 GiB resource retries. The interruption cause remains undetermined. Keep this ticket open until final outcomes reconcile its exact original body hashes and are published; aggregate recovery successes do not prove that every original deadline/memory case passed. Evidence: .cache/archive-release/ocr-recovery-20261113/{resume-state.json,restart-investigation.json,full/verification.json,final-summary.json}; final-summary.json is pending.

**2026-11-13T18:48:44Z**

Rewritten from the independent ETL/greybeard/evolutionary audit. Prior notes and evidence remain below; old running-job and automatic reread assumptions are superseded. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:06:57Z**

Offline completion 2026-11-13: ParserWorker now owns request-local RSS sampling (50 ms response loop; reset per parse, bounded retry included). Body outcomes label peak_rss_scope=request_sampled_worker_rss and retain worker_lifetime_peak_rss_bytes separately; historical outcomes remain unchanged. A real reused-process 64 MiB mmap request followed by a small request proves the second sample does not inherit ru_maxrss. The sample includes live retained allocations and may miss sub-50 ms peaks; it does not claim allocated-byte cost or process-tree memory. Removed the duplicate _MeasuredWorker sampler. Focused producer/worker regression: 30 passed (partial production-offline lane), measured 0.74 GiB peak RSS / 0.65 GiB physical. Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/pdf-offline-20261113/resource-tests-memory.json. Original identity reconciliation, remaining 210 OCR outcomes and publication acceptance remain open; OCR was not resumed.

**2026-11-13T21:20:54Z**

Final exact-commit offline verification at a96d5b88:124 passed,1 Vision declaration test deselected (partial six-file lane),0.75 GiB peak RSS/0.78 GiB physical. Read-only reconciliation of all31 retained original decisions gives28 completed candidates,2 memory_limit outcomes (1ebf2aeb...,d1203c08...),1 FzErrorFormat (4f57c7ee...); carried-completed.json accounts for af36b581.... No source-qualified replacement was inferred from completion. Every original decision and old outcome is preserved. Direct author data review, exact artifacts/hashes and smaller remaining gates for each owned ticket: .cache/archive-release/ocr-recovery-20261113/repairs/pdf-offline-20261113/{data-review.md,artifact-hashes.json,resource-original-reconciliation.json,final-tests.xml,pause-preserved.json}. Five frozen hashes still match and no recovery process runs.
