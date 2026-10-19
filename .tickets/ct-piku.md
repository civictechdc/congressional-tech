---
id: ct-piku
status: open
deps: [ct-2d3k]
links: [ct-d3un, ct-esm4]
created: 2026-10-19T16:40:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [overlap-followup]
---
# Make recovery runtime imports belong to the declared runtime

Dispatcher load 37-41 executes an explicit file, but sys.path mutation 103-105 and preexisting sys.modules determine transitive package/helper imports. The alternate-runtime phase test stubs load/builder/publisher, so it does not establish the promised pinned-runtime ownership.

## Acceptance Criteria

- Use one maintained package entry point or an isolated explicit runtime loader with verified transitive import owners.
- A selected alternate runtime cannot silently reuse ambient congress_api, filename helpers or control helper modules.
- Keep exact runtime pins and current explicit resume refusal; unsupported runtime states fail before writes.
- Test an alternate runtime with conflicting ambient modules and verify clear diagnostic or isolated correct owners.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/dispatch_corpus_recovery_publication.py:78:load. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data. Grok/Cursor is concurrently refactoring /scripts; use this ticket as its acceptance checklist and avoid duplicate implementation. Keep open until reviewed evidence passes.

**2026-10-19T17:00:42Z**

Related reshape ct-esm4 packages corpus recovery and pins the files that execute. Related only. It does not close this ticket.
