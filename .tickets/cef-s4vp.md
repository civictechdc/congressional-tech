---
id: cef-s4vp
status: in_progress
deps: []
links: []
created: 2026-10-28T07:55:35Z
type: bug
priority: 1
assignee: mikewolfd
---
# Match acknowledged record MD5s with provider ETags

Daily raw records return an acknowledged unquoted single-PUT MD5, while provider LIST returns its quoted ETag. Compare these known record checksums by normalized MD5 while keeping every non-record provenance ETag opaque and exact. Preserve current-inventory refusal and no payload reads.

