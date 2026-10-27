---
id: cefr-p8ec
status: in_progress
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
