---
id: ct-nkw9
status: open
deps: []
links: []
created: 2026-11-01T20:08:14Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [docs, phase2]
---
# Update the data model, annex and fixture manifest to the implemented state

docs/engine-first-data-model.md lines 5-10, annex §4.7 and model/fixtures/manifest.md still call the accepted review corrections unimplemented or planned, while their tickets are closed.

## Design

Map each GB row in the fixture manifest to the test that executes it, and name any case with no test. Run those tests on the pinned eb40c54 runtime. Update the three documents only for what that shows.

## Acceptance Criteria

- Each GB case names an executing test or is listed as a gap.
- The documents state implemented and live status separately.


## Notes

**2026-11-02T14:38:27Z**

2026-11-02 (lead): docs pass drafted on r4-docs (8 commits, each merges cleanly with every branch): data model, annex, switch plan, manifest (GB cases mapped to tests), emulated-only speed targets, and AGENTS.md's committee-code owner. Conflicts resolved by the lead: link successors use the same-body/fingerprint rule; a 206 counts only when complete. Final commit after all merges; live wording after the switch.
