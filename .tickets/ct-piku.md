---
id: ct-piku
status: closed
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

**2026-10-19T19:55:00Z**

Implemented selected source ownership admission before execute-mode imports, full package source existence/containment checks, foreign/unknown cached module refusal, real builder/publisher and explicit-file child checks before lock/client, and cached boundary observations. Exact baseline b879ba6 and same 319-file/3,559,245-byte fixture: all 8 unsafe baseline cases reached client/admission; candidate refuses all 8 before both. 25 warm checks issue zero path resolutions (0.453 ms median observed); complete pins add 58 files/330,101 bytes per existing digest guard. Focused 38 passed + 5 subtests; affected suites 246 passed + 7 subtests. docs/experiments/efficiency-debt/runtime-ownership.md and evidence JSON bind primary runtime-ownership/before.json + after.json. Local-only sentinel tests; no real client/remote operation or speed claim. Keep in_progress pending independent review/integration.

**2026-10-19T19:58:38Z**

Independent review approved 0affd10. Integrated selected runtime ownership with local event owner at fd8eb4d; 92 local integration tests and 5 subtests passed. All 8 unsafe runtime cases refuse before admission/client creation; added pins are a correctness cost, not a speed claim. Evidence: docs/experiments/efficiency-debt/runtime-ownership.md.
