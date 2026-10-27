---
id: cefr-wzxu
status: in_progress
deps: []
links: []
created: 2026-10-27T18:36:48Z
type: task
priority: 2
assignee: raw
---
# D3: produce versioned filename readings through native work lists

Owner reassigned D3 to raw. New producer uses house-naming unchanged and shares one SQL effective-name definition with E.

## Acceptance Criteria

Shared effective-filename SQL; distinct raw/provenance work anti-join; bound parser typed keys and stable errors; complete version digest; focused fixtures; native append binding and live backfill owner command.


## Notes

**2026-10-27T19:44:05Z**

Local native binding passes 132 producer/golden tests with engine-6fc6a94: nested Iceberg append, repeated-work no-op, plain JSONL unreadable rebuild exclusion, bounded-worker protocol injection and CLI authority guards. Production ParserWorker implementation remains engine-owned and pending; default import fails closed. Independent CODE and ARCH reviews requested before closure.
