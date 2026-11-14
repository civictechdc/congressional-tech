---
id: ct-a73a
status: in_progress
deps: []
links: [ct-m704, ct-kfsd, ct-n3ik, ct-hz8y, ct-yy07, ct-t4p3, ct-55qo, ct-aitp]
created: 2026-11-10T05:38:12Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, ocr]
---
# Reconcile resource-failure recovery and measure memory per request

The original defect affected seven paused page deadlines and seven 1 GiB memory-limit decisions. The source fixes have landed: page deadlines use user CPU time and the producer has a separate worker budget. Data acceptance remains open until those original identities are reconciled. The old recovery remains frozen after 2,426/2,632 committed outcomes, including four later completed bodies beyond the original pause. On 14 November the user authorized background OCR/refetch. Its 206 remaining PDF keys are running in a separate current-policy lane with durable page checkpoints; the old worker lacks these checkpoints and stays stopped. The new unlimited-size PDF policy is e7af136c37deb9d3bab5a3e9f3d4c79a4f5b38bd8b8f820aba5ec175672826dc, distinct from old d6250c3c… outcomes.

## Design

Retain the original cohort and all superseded decisions. ct-55qo owns qualified selection and ct-aitp owns page reuse. The audit found _child_peak_rss_bytes uses process-lifetime ru_maxrss in reused workers: resetting the supervisor sample does not reset that peak. Measure request-scoped memory before ranking individual bodies or raising admission limits; preserve old observations as lifetime measurements. Keep extraction errors separate from resource failures and unreadable decisions.

## Acceptance Criteria

1. Reconcile every original deadline/memory identity to a qualified completed reading or explicit measured unresolved outcome; supersede decisions with provenance only where justified.
2. Preserve the running-time deadline and independent pool-budget regression checks.
3. Request memory measurements are not contaminated by an earlier large request in the same worker; report measurement limitations and worker policy.
4. Under the 14 November authorization, finish only the explicit remaining recovery inventory under resource supervision, using ct-aitp checkpoints and ct-55qo selection. A source fix alone does not close this ticket.

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

**2026-11-13T22:24:49Z**

Native-only source diagnosis of two separate damaged bodies distinguishes format/source gaps from resource failures. PyMuPDF had already attempted repair; qpdf can produce a syntactically valid file that loses retained content. The Walling original contains useful earlier-revision testimony, but its later image stream is cut short. These two bodies are not the remaining 4f57c7ee... identity in this ticket's original 31-decision inventory, so this review credits no deadline/memory acceptance and supersedes no unreadable decision. Keep exact original-identity reconciliation and paused runtime gates open. Source/capture-history findings belong to ct-en4n; bounded evidence is <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/native-pdf-repair-20261113/data-review.md. No worker limit change, OCR, publisher request, selection or checkpoint reuse occurred.

**2026-11-14T05:39:37Z**

The final 66 completed recovery outputs now have additive stored-output integrity checks at repairs/corpus-assessment-20261113/tail-integrity-20261114/receipt.json. Combined with the earlier 1,250-row receipt, this covers all 1,316 completed outputs. The new check verifies text hashes/UTF-8 byte counts, page offsets and OCR provenance without repeating recognition or replacing the frozen run evidence. Native membership independently matches exactly 2,399 reading keys / 1,316 text keys. The independent metadata reviewer approved both packets; report: repairs/corpus-assessment-20261113/current-reconciliation/reviewer-shared-reader/independent-review.md.

This closes the named integrity/membership evidence gaps, not source transcription or selection acceptance. The paused inventory remains 1,083 errors, 23 unreadable decisions and 210 held targets. No OCR/provider run or publisher refetch resumed.

**2026-11-14T05:52:05Z**

Operational correction: a separate process removed the pause guard at 05:34 UTC and restarted the frozen recovery at 05:40 on 14 November. The coordinating task did not authorize that restart. Root restored the guard, blocked automatic follow-up and used the existing safe boundary pauser; recovery stopped after batch207 at 05:50. Four more completed outputs committed before shutdown: 2,426 total outcomes, comprising 1,320 completed, 1,083 errors and 23 unreadable, with 206 pending. All seven identified recovery processes exited; all five frozen source pins still match. No final verification, resource retry, selection or publication followed.

The earlier 1,316-output integrity receipt and census remain valid at their frozen batch205 scope. The four later outputs are separate, unqualified results and must not inherit those checks. Original control files and the incident record are preserved under coordination/pause-conflict-20261114/; current pause proof is coordination/pause-preserved-final-20261114.json. OCR remains paused. A generic assistant continue/resume does not lift the recognition pause.

**2026-11-14T06:04:59Z**

Separate batch207 metadata and committed-output integrity packets are now frozen. All four exact PDF reading/text pairs pass hash, UTF-8 byte-count, ordered/in-range offset and unique/in-range OCR-provenance checks: 4,394,643 text bytes, 1,947 stored page slots and 1,772 OCR entries, at the original d6250c3c… recovery version and macOS build 25G5057c. The existing verifier semantics were reused on one 1,428,124-byte immutable Parquet file with one-row batches; peak 0.064 GiB RSS, 0.6 seconds, unchanged 6 GiB admission floor. Together with the earlier receipts, all 1,320 completed recovery outputs now have stored-output integrity coverage.

Root read all four receipt records and the actual first 400 output characters of 2b0e1e4d…, a FY2026 Labor/HHS/Education appropriations hearing opening. This is output inspection only, not source comparison or an accuracy judgment. The staged body-text file is absent, so staged-to-committed parity remains unknown. The original batch205 pause record is preserved at its exact pinned hash; the frozen input manifest remains unchanged and a separate relocation record names its preserved path. Evidence: repairs/corpus-assessment-20261113/{late-batch207-20261114,late-batch207-integrity-20261114}/. The four new outputs remain outside the prior feature generation and source reviews; no reading qualification, selection or publication followed. OCR remains paused with 206 targets pending.

**2026-11-14T15:08:53Z**

Targeted OCR resumed at 2026-11-14T14:59:23Z in repairs/ocr-checkpoint-resume-20261114/, using clean pinned checkout09fdca797bc5428af7eaec9cfdfd32bb824f7fad and exact206-key manifest SHA66f5254222ddbd4f112709b34c51154a80738d972fe038c7716a4446df4513a1. New PDF recovery version e7af136c37deb9d3bab5a3e9f3d4c79a4f5b38bd8b8f820aba5ec175672826dc has unlimited input-size policy and actual page checkpoints. First1158-page target dbaa560cf220b77d9ea839faaf6485675a5e38b92f2d6fa31c6068a48a20ceab is writing durable pages under one4GiB worker and6GiB watchdog; final outcome still pending at this note. Old206pending keys and oldpause receipts stay frozen. Agent /root/regs_local_boundary_review supervises measured one-body acceptance before serial background continuation. Runtime completion is separate from useful-text qualification.

**2026-11-14T15:11:06Z**

First checkpointed body committed and verified at 2026-11-14T15:07:24Z: 1,158 pages / 1,106 OCR pages, 2,653,819 UTF-8 bytes, exact native/staged text SHA d105d199bb5cf5ee7f05dce60d06133737d8cb3add0f8cee556c2bb078e9780e. All1,158 page digests and source-page identities validated; checkpoints occupy41,926,040 bytes. Measured pilot481.9seconds /1.229GiB RSS, verification2.9seconds /.162GiB. Evidence: repairs/ocr-checkpoint-resume-20261114/pilot-verification/receipt.json. Remaining205 will run serially with one-body watchdogs, releasing shared nightly lock between documents. This is operational integrity, not manual transcription qualification.
