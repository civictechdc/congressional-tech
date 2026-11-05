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

