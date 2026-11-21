---
id: ct-f6qv
status: closed
deps: []
links: [ct-lwxs]
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


## Notes

**2026-11-20T23:23:54Z**

2026-11-20 branch handoff. Commit e8e7eaed5f70ac31e5f096e5b1a62ad4ec57f382 restores docs/plans/org-entities-20261108.md from 90bfd9378bd975bfcacf174cff39cb993ec95d2c and fc692aece3497078a0d63f8d4d5ac6204263467b against main 8c7b0e3f. The current release publishes 102,438 people and 57 historical person aliases. The plan links reviewed organization spellings to appearances, retains the source wording and keeps organization decisions out of person grouping. The companion source-read qualification is docs/plans/witness-identity-next-slice-20261120.md and <main checkout>/.cache/archive-release/long-tail-20261120/senate-id/ct-kt2o-qualification.json.

All five archived IDs were absent on main. Re-filed the original implementation epic ct-lwxs and its four children with the original dependencies. They remain open for the foundation (ct-6him), pinned RefSpec agencies (ct-w34j), reconciled Wikidata evidence (ct-39u8) and public organization lookup (ct-lvdf). This change delivers their plan and tickets. The remaining ct-f6qv criterion is integration of the plan into main.

**2026-11-21T01:32:50Z**

Integrated onto main cleanly; docs/plans/org-entities-20261108.md (updated for people.parquet) and re-filed implementation tickets (ct-lwxs, ct-6him, ct-w34j, ct-39u8, ct-lvdf) are on main with no org code.
