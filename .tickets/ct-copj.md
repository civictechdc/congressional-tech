---
id: ct-copj
status: in_progress
deps: []
links: []
created: 2026-10-20T18:37:15Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, transport]
---
# Preserve bounded request deadlines in the native HTTP path

Persistent HTTP removes subprocess overhead, but socket read timeouts do not preserve the old aggregate request deadline. Investigate supported native HTTP cancellation/deadlines and a trustworthy bound-listener readiness handshake. Keep the adapter thin and native recovery state intact.

## Acceptance Criteria

Stalled and slow-progressing metadata/Arrow requests stop within the documented request bound; partial Arrow cannot succeed; native retained completion remains recoverable and other host users stay safe. Use maintained async/HTTP primitives, no private socket internals, automatic retries or weakened pin checks. Local native/client regression tests and independent review.

