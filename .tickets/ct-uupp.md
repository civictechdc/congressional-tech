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

