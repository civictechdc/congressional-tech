---
id: cefr-deta
status: in_progress
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

