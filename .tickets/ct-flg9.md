---
id: ct-flg9
status: closed
deps: []
links: [ct-vq2a, ct-yci9]
created: 2026-11-05T02:36:33Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model]
---
# Five documents whose identical copies name two different bills

Under saved-copy-identity, 5 documents have same-bytes copies with different valid bill package names (e.g. BILLS-119hr2225ih vs BILLS-119hr225ih); earliest fetch wins. List: .cache/archive-release/investigations/saved-copy-identity/replay.parquet / copy-facts.parquet.

## Acceptance Criteria

Check each against GovInfo; decide a rule (e.g. agree with the meeting's measures) or publish no package when copies disagree.


## Notes

**2026-11-05T13:09:52Z**

Corpus review expanded the original five-case list to eight conflicting bill identities. At qualified source 7f9ebddd, conflicting filename-only bill claims leave package_id unresolved; stronger GovInfo address evidence remains authoritative, source claims remain available, and all seven same-bill version controls preserve their selected package. Independent covers and wrong-ID plants passed. H.R. 225 remains unresolved in the package field because its captured filenames disagree. Bounded native window plan, full corpus output and actual MCP/browser checks pass for candidate e145d24c389e. Publication remains pending the previously reserved owner cause review. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/{document-identity-repair,final-lane-repairs,candidate-streaming-repair,final-acceptance}/.

**2026-11-05T15:45:07Z**

All eight conflicting filename-only package IDs are empty in the live release; seven same-bill version controls retain their IDs. The official-source criterion is complete: inspected all 16 competing GovInfo introduced-version PDFs and checked Congress/number on each cover. Two captured PDFs match official bytes, five agree on a cover number with different bytes, and one unnumbered DeOndra Dixon draft is distinct from both official same-title bills. Source claims remain available. Exact per-case evidence: publication-approved/bill-govinfo-review/{REVIEW.md,review.json}. Published and independently verified in e145d24c389e (2026-11-05), replacing e4538f00. Qualified source 7f9ebddd; publication source 0d517fd5. All three offline shards passed (11,497 tests), full native/storage lanes passed, all six data suites passed, and all 26 public assets match the approved bytes. Live checks passed 180 MCP assertions and 57 deployed-browser assertions. Release note: docs/releases/2026-11-05-e145d24c389e.md. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/.

**2026-11-05T20:08:15Z**

November 5 scope distinction: the eight disagreeing-filename cases and their accepted e145 controls remain this closed ticket's completed work. Body f984b8439d21b0ef has two agreeing but wrong 4775 filenames, so the disagreement guard does not apply; its measure association is also derived independently. [ct-yci9](ct-yci9.md) owns the new content-supported package/measure decision and public acceptance. Preserve this ticket's closure and historical proof.
