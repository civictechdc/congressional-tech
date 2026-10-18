---
id: ct-eauq
status: closed
deps: []
links: [ct-gesp]
created: 2026-10-18T19:25:06Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Require a fresh output directory for direct viewer builds

The direct builder permits an existing output directory and overwrites generation files before replacing its manifest. A failed direct rerun can leave the old manifest referencing partially replaced files. The durable wrapper already supplies a fresh owned directory.

Source: apps/site/scripts/publish-filename-viewer.py:153-157; scripts/viewer_publication_attempt.py:37-100.

## Acceptance Criteria

Enforce a fresh owned target or build in a sibling directory and install only after verification. A failed direct build must preserve a previously valid publication. Keep the durable-wrapper route compatible and explain recovery in CLI errors.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 1 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:310). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:10:35Z**

Direct publication rejects nonempty/symlink output before any input or write, with new-target recovery error. Fresh existing empty wrapper directory remains supported. Test preserves prior manifest bytes; 7 pair/builder tests passed.
