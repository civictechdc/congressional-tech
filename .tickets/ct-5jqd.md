---
id: ct-5jqd
status: open
deps: [ct-2d3k]
links: [ct-d3un]
created: 2026-10-19T16:40:42Z
type: task
priority: 3
assignee: mikewolfd
tags: [overlap-followup]
---
# Report bounded per-object reconciliation progress

Continuation.reconcile 236-256 performs complete current-byte verification but emits no per-object progress. Aggregate status cannot distinguish a long supported scan from stalled reconciliation; serialized recorded verification must not become current proof.

## Acceptance Criteria

- Expose bounded object key/read/reconciled/conflict progress and an exact next check while retaining full body verification before success.
- Observe only: progress cannot grant write authority, trigger replay, or claim public verification.
- Committed/uncommitted/conflicting outcomes, fresh-client proof and full-read fallback remain; no credentials in diagnostics.
- Test partial read/failure progress and completion ordering using retained bounded fixture.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/recovery_publication_continuation.py:102:Continuation.reconcile. See docs/package-overlap-rescore-20261019.md for the full grade map.
