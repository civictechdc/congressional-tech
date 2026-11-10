---
id: ct-f7hp
status: in_progress
deps: []
links: [ct-vq2a, ct-94hw]
created: 2026-11-10T03:42:38Z
type: bug
priority: 1
assignee: mikewolfd
tags: [data-model, correctness, release-blocker]
---
# A newer identical copy renames a document and drops what its filename said

Release candidate at 8c3a3cae against live 630164505301: 621 documents take the filename, kind, family and facts of a byte-identical copy first fetched on 2026-11-08 at another address (democrats-edworkforce.house.gov, budget.house.gov), because model/sql/saved-files.sql leads the saved body with its newest-fetched source file. 576 of the names lose information (322 lose a House-convention name). The saved body, Congress, committee, meeting and date are unchanged (ct-vq2a took those from every copy). ct-94hw recorded the same behaviour as explained on 2026-11-04 (1,689 documents).

## Acceptance Criteria

A later capture of bytes the archive already holds never renames a document or changes its kind, family or facts; a recovery-only document later captured live at its original address still takes that address; the published address never goes blank; the saved body does not change. Measured effect against the live release recorded before any model run.

