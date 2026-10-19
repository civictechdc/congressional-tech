---
id: ct-yifn
status: in_progress
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

## Notes

**2026-10-19T16:44:52Z**

Implemented one retention.body_keys.body_key_digest parser for aliases, retained-body reads and explicit completed-PDF reading admission. Existing boolean/None wrappers, false missing values, nonempty wrong-type TypeError and explicit PDF ValueError remain intact; valid digests still verify exact source bytes. Only the body-reading admission hunk changes document_index.py. All 88 focused key/alias/evidence/PDF refresh checks passed. Primary log: output/package-overlap-rescore-20261019/browser-package-body-keys.log. Awaiting independent review.
