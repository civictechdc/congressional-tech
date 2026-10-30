---
id: cef-ykpg
status: closed
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


## Notes

**2026-10-27T04:27:05Z**

Local contracts cover every required status and refusal of non-probe buckets. Owner command: .venv/bin/python -I -m congress_api.cli.raw_lock_probe --bucket cx-engine-first-lock-probe-OWNER --execute, after installing an indefinite bodies/ lock on that disposable bucket. No real probe run. Conditional duplicate must return 412 before applying raw locks; preserve other bucket lock rules.

**2026-10-30T14:32:56Z**

Completed B1 bucket-lock qualification and applied R2 object locks.
