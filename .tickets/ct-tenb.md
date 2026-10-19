---
id: ct-tenb
status: in_progress
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:38:43Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Confine restored publication phase files to their attempt

Restored non-inventory phases hash saved paths without the confinement check used for new phases. A matching external symlink can escape owned storage.

## Acceptance Criteria

Reject file and parent symlink escapes before hashing or accepting restored outputs. Preserve matching owned files, issued inventory reuse and existing digest checks.

## Notes

**2026-10-19T16:43:22Z**

Restored non-inventory phase files now repeat file-symlink/resolved-root confinement before hashing. Matching owned files and digest refusal remain covered; file/parent symlink escapes refuse before hashing or checkpoint changes. State/continuation/attempt regression suite: 60 passed. Awaiting independent review; ticket remains in progress.
