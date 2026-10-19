---
id: ct-2ut4
status: open
deps: [ct-2d3k, ct-v6ao]
links: [ct-d3un]
created: 2026-10-19T16:40:42Z
type: task
priority: 2
assignee: mikewolfd
tags: [overlap-followup]
---
# Give local recovery one event owner and derived progress

Local dispatcher journal 78-82 mutates continuation state and appends/fsyncs separate events.jsonl. Its receipts intentionally remain local, but overlapping representations still obscure which record owns uncertain-write/phase progress. Cloud remote-journal restoration does not reduce this local path automatically.

## Acceptance Criteria

- Choose an explicit local event authority with derived bounded progress/checkpoint state.
- Retain exact local uncertain-write facts, phase acceptance, failed-attempt evidence and required fsync boundaries.
- Do not require cloud artifact custody or remote durability for a deliberately local route.
- Measure local serialization/fsync work and test resume after every accepted phase and uncertain write.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/dispatch_corpus_recovery_publication.py:113:run.journal. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data. Grok/Cursor is concurrently refactoring /scripts; use this ticket as its acceptance checklist and avoid duplicate implementation. Keep open until reviewed evidence passes.
