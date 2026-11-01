---
id: ct-qg8e
status: open
deps: []
links: []
created: 2026-11-01T20:08:13Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, qualification, phase2]
---
# Explain publish_v21 row-count changes against release c94bfedc

Between c94bfedc and 448651e7: list 367,008 to 427,517; sources 605,848 to 537,077; links 439,555 to 432,320; bills 11,832 to 13,234; witnesses 147,048 to 147,888; url_state 1,201,754 to 1,198,835. No ticket explains these.

## Design

Compare the two public releases by key, not by count. Classify added and removed rows by cause (recovery round, URL normalization, parser changes, upstream generation). Then re-measure ct-opy0 and ct-db3w, which were measured on c94bfedc.

## Acceptance Criteria

- Every added or removed row group has a recorded cause and count; anything unexplained is listed as a defect.
- ct-opy0 and ct-db3w carry numbers for the live release.

