---
id: ct-kwse
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T20:47:30Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness]
---
# Document date taken from a bill title year in the filename (Batcheller testimony dated 2019-06-23, should be 2020-06-23)

Nightly candidate ef4c1632: after the saved copy swapped, the BatchellerG statement (base: HHRG-116-II13-Wstate-BatchellerG-20200625.pdf, dated 2020-06-25 from the filename) is dated 2019-06-23 from 'Bear Protection Act of 2019' in the new filename, with status accepted. Same saved-copy swap as the package_id ticket. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/05c-possible-defect-document-date.json.

## Acceptance Criteria

A year that is part of a bill/act title is not read as a document date; the document keeps 2020-06-25 (or meeting date). Fixture with an 'Act of YYYY' filename.

