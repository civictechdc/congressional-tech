---
id: ct-adtz
status: open
deps: []
links: [cefr-3w18]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, reviews, b8, provenance, track3]
---
# T3.4 (B8): Rebind interactive document review forms to review_provenance.py

Per docs/plans/simplification-plan-20261024.md §6.2.8 and docs/plans/bindings-20261025.md §6: update the interactive document review forms so reviewer verdicts write provenance/reviews/ JSONL records via packages/viewer_publication/src/viewer_publication/review_provenance.py rather than coupling to the legacy catalog.

## Acceptance Criteria

Reviewer verdicts from interactive review forms emit provenance/reviews/ JSONL records schema-validated by review_provenance.py with no dependency on the legacy catalog.

