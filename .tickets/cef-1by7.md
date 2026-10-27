---
id: cef-1by7
status: in_progress
deps: []
links: []
created: 2026-10-27T19:51:03Z
type: task
priority: 1
assignee: mikewolfd
---
# Stage body readings through native work lists and appends

D2 local producer slice: native deduplicated body/parser/version worklist and active unreadable anti-join, ranged sniff adapter, bounded page reads and supervised parsers, raw unreadable staging, native typed output and C7 append. Live backfill stays owner gated; local duplicate/noop/version/error/size/nested link fixtures pass before review closure.

