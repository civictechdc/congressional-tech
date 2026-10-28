---
id: cefr-p8ec
status: closed
deps: []
links: []
created: 2026-10-27T13:54:32Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B2: file-based raw fetcher, archive expander and receipt writer

## Acceptance Criteria

Explicit scope and pacing policies; bounded file-backed transfers; typed receipts after bodies; archive refusal facts; focused contract suite passes.


## Notes

**2026-10-27T14:08:16Z**

Core components implemented through be8605b0; required contracts landed first. Focused B2 group: 114 passed, 1 duplicate-member fixture warning. No live jobs/credentials/network writes. Independent code and architecture review pending with raw parent; leave ticket open. Evidence docs/measurements/engine-first-20261027/b2/README.md and scratch codex-raw/b2-plan/cxb_b2_group.log.

**2026-10-27T14:18:40Z**

Independent B2 code-review findings fixed: contract regressions 1cc57e84 (5 failures reproduced), provider completeness 56785668, independent/observable host waits 800533e9, explicit ZIP/RTFD view lifetimes c6dc8e72. Accepted B2+existing sniff/archive/Foundation-wrapper/import-fence runner: 133 passed, 1 expected duplicate-name fixture warning, 2.70 seconds; scratch b2-plan/cxb_b2_review_fixed_group.log. Correct source line counts for 800533e9 are fetcher.py 150 to 158 (its commit body misstated them). Architecture review remains pending; ticket stays open.

**2026-10-27T14:20:01Z**

Final review-fix group includes provider206/content-range through Fetcher and published ReceiptWriter: 135 passed, 1 expected duplicate-member fixture warning in 3.57 seconds. Latest log b2-plan/cxb_b2_review_fixed_group.log. Public APIs unchanged; architecture review pending.

**2026-10-27T14:27:37Z**

B2 architecture concern fixed: contract1526907d reproduced both empty/member ZIP comment-signature failures; extraction now reuses the preflight-selected bounded _ArchiveView through ZipFile. Focused archive/sniff/Foundation-wrapper/import-fence runner100 passed/1 expected duplicate-name warning in12.96s; evidence b2-plan/cxb_b2_eocd_fixed.log. No public API/spec changes; architecture finding addressed.

**2026-10-27T15:38:48Z**

Local done: typed file-backed fetch/receipt/archive contracts pass135 checks; bounded ZIP-view fix passes100 focused checks. Code and architecture findings reproduced before fixes and resolved in56785668/800533e9/c6dc8e72/42eb6537/e273e22a. F2 wiring and hosted/native transport qualification are separate; no live capture ran.

**2026-10-28T01:49:38Z**

Acquisition review correction underway: transfer-only fetcher; receipt writer must acknowledge body storage before optional fallible inspection and retain explicit unknown/pending sniff failure facts. Contract-first local synthetic run expected red: 14 failed in 3.30s across F2 group. Archive expander and transfer retry/completion policy remain outside this slice.

**2026-10-28T01:53:21Z**

Review correction implemented after contract af44f627: acquisition returns transfer facts, then ReceiptWriter inspects only after body-store acknowledgement. Known read/resource failures retain exact durable body+receipt, stable sniff_error and unknown verdict; transfer complete/outcome and provider fallback stay unchanged. Successful capture-time sniff facts remain for D1/D2. Focused84 plus sniff/pending36 pass on approved486runtime; parent review pending. Archive-member inspection/expansion unchanged; no live action.

**2026-10-28T03:34:02Z**

Reopened durability concerns fixed: body PUT precedes sniffing; known inspection failure defers archive expansion and retains durable error receipt; source/member facts publish only for completed maintained-sniffer status. Contract-first fixes and CODE-approved0e0ab719. Combined104 focused checks PASS19.25s on9b59263; no live capture or network writes.
