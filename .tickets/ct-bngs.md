---
id: ct-bngs
status: open
deps: []
links: []
created: 2026-11-24T18:21:46Z
type: chore
priority: 2
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, git]
---
# DocMeta V7: Checkpoint & PR uncommitted work in congressional-tech and fast-silicon

Review, split cleanly by concern, and commit/PR uncommitted changes across both repos: (1) fast-silicon fast-ocr FPDF_PAGEOBJ_PATH + dense vector-outlined native router fix and CPU tests (keep separate from unrelated pre-existing uncommitted work); (2) congressional-tech DocMeta V7 package, release contract, ct-o7ew OCR rescue tool, V7 tests, and 82-file V4-V6.5/docmeta_v6_1 retirement.

## Acceptance Criteria

Clean commit(s)/PR(s) scoped without unrelated drift; scripts/dev.py doctor, scripts/dev.py inventory, and affected offline suites pass cleanly in both repos.


## Notes

**2026-11-25T04:45:53Z**

2026-11-24: congressional-tech side checkpointed, reviewed, refined, and opened PR from rebased feat/v7-org-warc-viewer onto origin/main (covering ct-ogcq, Org Entities Phase 1, DocMeta V7 core/factory/OCR rescue/9K unification/V4-V6.5 retirement, and the DocMeta V7.3a.1 viewer). Remaining scope for ct-bngs: fast-silicon repo commits/PR.
