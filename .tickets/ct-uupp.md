---
id: ct-uupp
status: open
deps: []
links: [ct-kunv, ct-9gmr]
created: 2026-11-02T15:55:30Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [captures, memory, etl, phase2]
---
# Capture staging memory grows with receipt size; stage oversized receipts in bounded line ranges

spec-run 2026-11-02: D1 batch 3 is the single assembly receipt receipts/documents/undated/assemble-20260930.jsonl.gz (581 MB uncompressed, 808,680 captures). Staging it went from 8.0 to 16.5 GiB RSS in 1.2 s, and the guard killed it at 16 GiB; batches 0-2 peaked at 5.9, 5.3 and 2.7 GiB. The e2 plan measured the assembly receipts at about 20 GiB pool and 24 GiB physical. Memory is O(receipt size), not bounded by the batch budget.

## Acceptance Criteria

Staging splits a receipt above a byte or line threshold into line ranges, with resume per range and identical output to whole-receipt staging (a test proves equality on a split receipt); peak RSS on the 581 MB receipt is bounded (measured) at the normal batch budget.


## Notes

**2026-11-02T15:56:08Z**

2026-11-02 spec-run: two attempts on the 581 MB receipt. At guard 16 GiB the guard stopped it at 16.1 (physical 15.1); at guard 20 the batch monitor's 16 GiB physical cap (14 GiB pool, capture_backfill.receipt_profile) stopped it at 18.0 RSS / 18.8 physical. In both, RSS rose about 8 GiB in about 1 s, roughly 6 s into staging, before any engine step metrics, which points at Python-side receipt loading rather than the engine. Workaround for this run: pool 18 GiB (24 GiB physical cap), guard 24, per e2's plan; a profile of the jump is requested.

**2026-11-02T16:17:42Z**

2026-11-02 spec-run profile (correction to the earlier hypothesis): the jump is in the docspec engine, not Python. The Python CLI stays at 0.05-0.11 GiB; the docspec child goes from 0.42 to 17.1 GiB in about 6 s, peaking at 22.45 GiB RSS / 26.63 GiB physical at an 18 GiB pool, so above its own pool. Samples: jiter json_get_*/json_contains over receipt lines, string-view copies, memory accounting; the whole 581 MB receipt is decoded at once. Decision (lead): stage oversized receipts in bounded line ranges in the batching layer, not the mapping, so APPROVED_MAPPING doesn't move; output byte-identical; implemented by etl-staging on r4-staging. An engine-gap ticket follows for JSON extraction exceeding the pool in RSS. Profiles: .cache/archive-release/r1b-run/logs/batch3-profile/.

**2026-11-02T16:28:15Z**

2026-11-02 etl-staging: root cause found. DataFusion 53.1 array_concat on string views (the capture 'entries' step) grows with batch_rows². At batch_rows=1024 and a 14 GiB pool, the whole 581 MB receipt stages through the production CLI at 6.49 GiB peak with 808,680 rows; the other 9 oversized receipts peak at 1.0-6.2 GiB; A/B on 7 receipts at 8192 vs 1024 rows is byte-identical. Fix (lead-approved): a derived stage-limits file with batch_rows=1024 in capture_backfill on r4-staging (the mapping doesn't move), plus an engine ticket under ss-oxg1 to bound array_concat on views as ss-x71z did for array_agg. Line-range splitting isn't needed.

**2026-11-02T16:37:30Z**

2026-11-02 etl-staging r4-staging 8e0452a9: staging runs at most 1,024 rows per engine batch; the 581 MB receipt stages in 30 s at 6.49 GiB RSS (5.79 physical) at the 14 GiB pool, all 808,680 captures (before: never finished, over 22 GiB). Cause: DataFusion 53.1 array_concat over string-view lists (the mapping's entries step), quadratic in rows per batch and uncounted by the pool (32k-line slice: 0.15/2.2/>7 GiB at 1024/4096/8192). Byte-identical on 10 receipts (8192 vs 1024) plus a repo test (2 vs 8192); time 0.93-1.24x; APPROVED_MAPPING unchanged. Engine ticket ss-1rrn under ss-oxg1. Being made one shared cap for daily, backfill and CI staging. Line-range splitting not needed.
