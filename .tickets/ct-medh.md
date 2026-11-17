---
id: ct-medh
status: open
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, lake, gate5]
---
# One base check for the nightly's pre-check and gate 5; operator lake writes go through the pipeline

Root cause 4 of the 2026-11-17 RCA. lake/daily.py _producer_bases accepts any existing head record, while producer_proof judges it afterwards, so the nightly can append onto a base the gate then refuses, or leave state after an interruption that the gate rejects. Operator sessions also append to production tables under no lock the nightly shares (ct-z4w5 on 2026-11-17).

## Acceptance Criteria

The nightly refuses before appending whenever gate 5 would refuse its base, from one shared rule. Operator writes to production lake tables have one documented path that is serialized with the nightly.

