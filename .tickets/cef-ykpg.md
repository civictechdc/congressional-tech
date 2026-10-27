---
id: cef-ykpg
status: in_progress
deps: []
links: []
created: 2026-10-27T04:26:04Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, B1]
---
# B1: qualify bucket-lock operations on an isolated scratch bucket

## Acceptance Criteria

Local probe contracts pass; owner records real scratch-bucket statuses, conditional duplicate is 412, overwrite and delete are refused, and reads back indefinite lock rules for bodies/provenance then receipts after B0.

