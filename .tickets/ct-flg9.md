---
id: ct-flg9
status: open
deps: []
links: [ct-vq2a]
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
