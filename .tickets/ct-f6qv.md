---
id: ct-f6qv
status: open
deps: []
links: []
created: 2026-11-18T20:27:36Z
type: feature
priority: 3
assignee: mikewolfd
tags: [identity, witnesses]
---
# Link witness appearances to canonical organisation entities (revive ct-lwxs plan)

The plan docs/plans/org-entities-20261108.md and its five tickets (ct-lwxs and four children) exist only on archive/2026-11-18/claude/ct-org-entities-plan (commits 90bfd937, fc692aec); main has no organizations or witness_organizations tables. Decisions it records: token-bag keys, blocked fuzzy review, pinned RefSpec Federal Register agencies, Wikidata reconciliation. Its organisations-first premise is outdated because people.parquet (ct-ha10) shipped first; update it to feed reviewed organisation aliases to ct-kt2o. Review: .cache/archive-release/reviews/branch-value-20261118/a-ct-small/REPORT.md.

## Acceptance Criteria

The plan is on main, updated for people.parquet, with its tickets re-filed; no code yet.

