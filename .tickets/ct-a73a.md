---
id: ct-a73a
status: in_progress
deps: []
links: [ct-m704, ct-kfsd, ct-n3ik, ct-hz8y, ct-yy07, ct-t4p3, ct-55qo, ct-aitp, ct-l3xd]
created: 2026-11-10T05:38:12Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, ocr]
---
# Reconcile resource-failure recovery and measure memory per request

All 193 completed bodies from the separate stored-size recovery lane now have qualified selected text in accepted-set-v10. Thirteen historical archive-read failures remain recorded. The first source was recovered and its 1,208-page pilot passed mechanical checks, but direct source review found material OCR omissions; the candidate and remaining twelve dispatches are held. A distinct older group has nineteen memory failures: seventeen retry candidates and two selected same-URL alternatives needing revision comparison. Three earlier private handwriting completions remain held within the no-selected-reading inventory. Preserve the original run and all prior failures.

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

**2026-11-14T15:57:37Z**

Separate checkpointed lane at source 09fdca797bc5428af7eaec9cfdfd32bb824f7fad is running asynchronously under the explicit authorization. Snapshot at 15:49:17 UTC: 12/206 completed, zero reported errors,194 remaining; durable supervisor 57410 advances one body per watchdog and yields the shared nightly lock between bodies. First 1,158-page pilot:481.9 seconds / 1.229 GiB RSS,1,106 OCR pages,2,653,819 text bytes; all 1,158 checkpoint/source/digest identities verify. Terra medium directly read pages 10/300/600/1100; two dense pages have substantive omissions already before final cleanup. Operational completion does not establish quality. Exact three-band replay isolated both Vision non-detection and unique strip-edge discards; ct-l3xd owns the latter. Old outcomes and active policy remain unchanged.

**2026-11-14T18:47:50Z**

Restart evidence: ocr-checkpoint-resume-20261114/restart-20261114T182343Z/post-restart.json. Worker commit 09fdca797bc5428af7eaec9cfdfd32bb824f7fad and all 27 manifest pins are unchanged. Incomplete batch 50 remains intact; resumed body committed in batch 51. The reboot is verified, but the precise pre-reboot termination trigger is unknown. Recovered body watchdog passed at 0.972 GiB / 11.2 seconds. A frozen 56-completion screen passes structural integrity; two new garbling warnings remain unaccepted. Runtime completion does not prove source quality. At 18:43:49 UTC the separate lane had 59 completed outcomes, zero runtime errors and 147 remaining. The 56-row quality snapshot is a separate frozen prefix; later completions are outside that check.

**2026-11-15T04:46:39Z**

Current supervised continuation is repairs/ocr-checkpoint-resume-20261114/restart-20261115T035808Z/. A host-memory stop below the existing 4 GiB floor ended the prior supervisor; 76 saved pages were reused before recognition resumed at page 77. continue_targeted_v2.py retries only a no-commit watchdog-99 host-memory stop, at most three times with 30-second backoff and the unchanged memory admission. Six focused retry-policy checks pass. Completed outcomes 1-91 have exact-key integrity/quality screens in the original 56-body generation and two disjoint 20/15-body deltas. No empty whole output or new strong garbling signal appears in the two deltas. The earlier f6d8df26 word-fragmentation finding remains explicit and separate from runtime completion. Snapshot: 93 completed / 113 remaining at 2026-11-15T04:39:22Z; private results are not automatically selected or published.

**2026-11-15T07:05:12Z**

Current reconciliation separates the 206 original stored-size-limit targets (148completed/58remaining at2026-11-15T06:48:25Z) from 66 original memory/deadline targets. Of the latter 62 have selected completed readings;1ebf2aeb,d1203c08,4f57c7ee,b269f9d8 remain unresolved. A separate exact-key preflight is being prepared; the 206-target worker/manifest remain unchanged. Quality chain through145: repairs/ocr-checkpoint-resume-20261114/quality-screen-delta-20261115T064046Z/handoff-with-integrity.json SHA 4bc57e3c479437d2cf3eda5aa1d298403083b1f31cefb7209e95e6fcebe92757.

**2026-11-15T07:45:37Z**

2026-11-15 additive source-history reconciliation: preserve original incomplete4f57 and its error; same exact publisher URL has complete retained4e8115a7c06e2369bdf2eb4d2f3106593456d99259317d103254bc1060a70fee, selected completed d625 reading, 1,655,126 text bytes /1,038 slots/956 OCR markers and one visible association. Original truncated body has zero associations. Raw receipt/custody/selection evidence is repairs/resource-source-refetch-20261115/handoff.json SHA79a4974e7ac9fe047facaad9fa0e243cc9a501cf643afb7b764f976b883b8f4c. No new PDF semantic review or publisher request is claimed. Remaining three exact complete-capture resource failures have a separately pinned lane; root dispatched its one-body pilot at07:41:41UTC after verifying all35pins. Handoff repairs/resource-checkpoint-retry-20261115/handoff.json SHAd7b025ae1b8ba6622bda200896c7868fb1dba0eb824ecf904341d2e674bac600. Pilot waits shared nightly lock; current206worker and main selection are unchanged.

**2026-11-15T07:55:50Z**

The new d120 pilot committed unreadable/memory_limit at2026-11-15T07:43:19Z: request-sampled worker RSS4,331,323,392bytes against4GiB; watchdog peak4.079GiB RSS/3.332physical,98.9seconds, outerexit0. A successful driver exit is not completed text. No new completed reading or text was adopted, and no continuation was launched. Exact failure/diagnostics/checkpoints remain under repairs/resource-checkpoint-retry-20261115; cause diagnosis precedes any changed limits or next attempt. The206worker remains live and separate.

**2026-11-15T08:36:23Z**

Private quality chain now freezes 176 completed results: quality-screen-chain-176.json SHA eac2946616745135cc8f5581b23fd61f8592261c7193ba58f38868a5473def9b; delta handoff SHA e545ef9a08eedcdbd69ddf522dc9adb9a24fdbd4ac6f74fe0b0f97787e7042a5. Eleven new pairs add 17,528,369 UTF-8 bytes / 8,835 slots / 6,863 OCR markers, with all integrity checks passing, zero empty outputs and no new strong flags in 2.17 seconds / 0.21 GiB. None is selected automatically. Resource continuation02 retained memory_limit at request RSS 4,435,804,160 bytes but preserves 153 to 183 valid checkpoints; next page 184 of 215. All old checkpoints remain unchanged. Evidence: repairs/resource-checkpoint-d120-continuation-02-20261115/post-attempt-review.json. The other two resource bodies remain distinct and unattempted.

**2026-11-15T09:22:13Z**

All three remaining complete-source resource cases now finish without raising the worker limit: d120 215 pages / 407,695 bytes / 99 OCR markers; b269 123 pages / 48,200 bytes / 123 OCR markers; 1ebf 169 pages / 151,979 bytes / 169 OCR markers. Earlier memory failures and matching checkpoints survive. Independent review finds six held handwriting positions and three useful controls; 498 other source-page positions are unread. Additive hold: repairs/resource-source-six-page-review-20261115/additive-held-quality-20261115/handoff.json, SHA bd3810fd507dccbd5d0a83067debdaf544ad2b07ef6a8418fd6d0d499202a410. Vision confidence is not an acceptance gate here. The separate 206-lane quality chain covers 187 exact results without rereading the prior 176 payloads.

**2026-11-15T10:52:30Z**

Final recovery evidence: repairs/ocr-checkpoint-resume-20261114/quality-screen-chain-193.json (SHA ab38cf2e4f9205a78e029f09758372e8a977f85ae21afd0b2e00c3b2840efa29) binds 193 actual outputs / 228,840,708 UTF-8 bytes / 111,129 slots / 81,135 OCR markers. Five no-obvious, five first-review and 183 weaker-signal results are candidate quality bands, not automatic acceptance. The thirteen failed stored reads span 541,845,812–1,065,029,037 bytes; current one-byte ranges and SDK metadata match all retained identities. Thirteen application bytes were read in the diagnosis. No historical subcause is inferred from passing headers. Diagnostic code 981e932ebfee1ab90af6d6926db1931919affddf preserves pending semantics and versions; 95 offline plus five real HTTP/spawned-worker tests passed (partial lanes). Its independent review identified the need for a whole-attempt deadline on the proposed single-object transfer. Frozen workers/catalog/selection unchanged by that diagnostic work.

**2026-11-15T12:11:18Z**

Accepted-set-v10 selection SHA eb8473ab6163d3ab4b16f4fa56754a5b72b9391065aeedf3138db02eaaf3b111; native snapshots body_text 4383126096555098411 and readings 6734786965736914418. Independent result SHA 016d5932ef5a62d09a706974da210c7adb37e026efc19b8a833529f8568cd9d0 verifies all 388 new native pairs, append ancestry, all 1,217 prior choices, 339 prior disposition lines, preserved dbaa and rejection of a planted wrong digest. The new delta contains 234,583,311 UTF-8 bytes / 114,416 slots / 80,443 OCR markers. Source review covers 94 of those slots; 114,322 remain source-unread with exact limits retained. The old 206-target lane remains frozen at 193 complete / 13 pending. PR179 merged as 043d048c0588a04f7921301efd6ec9cf170def95 after all CI passed: complete pinned-object reads can accept HTTP200 with exact length/ETag, while partial ranges remain strict206. The original one-object pilot captured the rejected200; the repaired retry returned206 and all 541,845,812 stored bytes in 14.2 seconds at 0.637 GiB. Local bounded decoding verified 575,953,191 PDF bytes and body SHA 251ea1a6…; no new request was needed. The independent 1,208-page stage-only pilot uses fresh checkpoints under raw-range-retry13-20261115. The separate nineteen old d625 memory failures were originally failed_pages targets and are outside the earlier 66 memory/deadline cohort. Do not double-count d120/b269/1ebf: these three held completions are among 612 PDFs without a selected reading, outside the 83 selected PDF refusals.

**2026-11-15T12:27:39Z**

The 1,208-page pilot completed in 1,037 seconds at 1.756 GiB outer peak RSS: 1,174 OCR pages, 34 native pages and 2,196,023 UTF-8 bytes. All checkpoints and stored-output integrity checks passed. Terra medium directly read source, actual observations and final slices for pages 1, 2, 4, 5, 7, 302, 604, 906 and 1208. Material prose omission/garbling on pages 7, 302, 604 and 906 already exists in Vision observations. Hold whole-body acceptance and remaining twelve dispatches pending a one-page maintained-tool comparison. The other 1,199 pages remain unread. Evidence: repairs/raw-range-retry13-20261115/independent-source-review/{review.md,pins.json}. No catalog or selection mutation followed this pilot.
