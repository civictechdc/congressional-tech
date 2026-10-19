---
id: ct-yifn
status: open
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:35:49Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Use one retained-body key validator

Alias resolution, retained-body evidence and PDF-reading admission repeat the same digest/shard validation. Keep this domain rule in congress_api.retention.

## Acceptance Criteria

Three callers use one pure digest-or-None parser while preserving existing public wrappers, refusal behavior, type handling and source bytes. Cover bad shard, malformed digest, missing and valid keys.
