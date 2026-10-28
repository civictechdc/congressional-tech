---
id: cefr-deta
status: closed
deps: []
links: []
created: 2026-10-28T14:27:43Z
type: task
priority: 2
assignee: mikewolfd
---
# D1 distinguish vote outcomes from acquisition outcomes in record lists

Confirmed House meeting XML item kind vote uses domain outcome unknown. Add source-derived fixtures before a narrowly authorized record-list discriminator; production behavior held for lead and engine acknowledgment.

## Acceptance Criteria

Vote domain outcomes ignore only vote-item outcome, preserving line acquisition outcomes and derivation; other unknown acquisition values still refuse; schema and all other item facts preserved.


## Notes

**2026-10-28T14:42:39Z**

Contract b71237f0 produced five expected unknown-outcome failures with five controls passing before behavior. Lead142938 and engine143817 approved exact Vote-list rule. Behavior and DM6.1 committed bf1e6a05; focused68 passed237.15s on explicit c9 runtime-v2. Independent CODE review APPROVE, no findings. Source24/public34 and strict unknown acquisition refusals preserved. Actual freshcaption,50slice,200proof/full apply remain root-owned and held for independent engine correctness disposition.
