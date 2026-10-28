---
id: cef-94nn
status: in_progress
deps: []
links: []
created: 2026-10-28T14:12:52Z
type: task
priority: 1
assignee: mikewolfd
---
# Pass bounded native limits through the retained news CLI

Expose the existing DocSpecClient limits parameter on every retained news CLI operation so local and CI native integration tests can use one explicit host-sized profile without changing defaults, skips, assertions, or native admission. Verify parsing and the existing real native CLI lifecycle with explicit bounded limits.

