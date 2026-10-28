---
id: clef2-hvh4
status: closed
deps: []
links: []
created: 2026-10-28T10:23:23Z
type: task
priority: 0
assignee: mikewolfd
---
# Verify complete hosted shard evidence against the pinned landing baseline

## Acceptance Criteria

Read-only verifier requires six complete budgeted shard test runs, exact two-way36 identity baseline, no new failures and valid run head; operator window preserves red status and strict success for publish/Pages; focused tests and one review pass


## Notes

**2026-10-28T10:59:12Z**

Done locally: complete hosted evidence verifier preserves visible CI failure, reports observed/new/resolved identities, rejects partial/interrupted sessions and broken infrastructure; lead subset correction applied.96 focused checksPASS1.55s; review APPROVE phase-e03e934c closes every confirmed finding. CI exit producer separately APPROVE and merged engine089. Hosted execution/runtime/application acceptance remain lead gates; WINDOW_READY=0.
