---
id: ct-tenb
status: open
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
