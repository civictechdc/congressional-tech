---
id: ct-87uq
status: closed
deps: []
links: []
created: 2026-10-19T15:46:23Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-snh8
tags: [package-cleanup, behavior-preservation]
---
# Make document category mappings explicit and checked

Publisher document meanings, meeting categories and filename families intentionally differ. Establish a maintained mapping and consistency checks without merging source evidence with filename inference.

## Acceptance Criteria

All existing mapping outputs and classification precedence remain unchanged, including unknown and multi-kind values. Explicitly document coarse versus detailed mappings. Add exhaustive checks for the current mapping sets and focused consumer tests. No catalog rebuild, classification run or review changes.


## Notes

**2026-10-19T15:46:23Z**

Implementation authorized in an isolated worktree. Preserve source data and production workflows. Ticket closes after focused checks and independent review; parent tracks merge completion.

**2026-10-19T15:50:28Z**

Implemented category policy ownership in adapters/documents.py. Meeting, House and Senate adapters use the same owner; existing meetings.category, meetings.DOCUMENT_CATEGORIES and house.DOCUMENT_CATEGORIES names remain available. The category function AST matches b191fc8 exactly. House's code map preserves the SD exclusion. Literal publisher meanings, collector mappings, filename families/rules and normalized model/schema/version remain unchanged.

Captured the fixture from unchanged b191fc8 before edits, then independently re-evaluated the base source via git show to verify its provenance: 46 publisher aliases, 19 collector meanings/XML codes, 20 Explorer meanings, 18 House XML mappings, and 61 mapped filename kinds in 17 families. Coverage checks retain intentional questionnaire/summary omissions; consumer tests cover all aliases, conflicting titles, every title keyword pair, unknowns, exact-label priority, multi-kind order/dedup and retained source values/evidence. docs/congress-api-contracts.md documents the maintained owners and intentional differences.

Validation in this worktree's own uv sync --frozen environment: .venv/bin/python -m pytest -q tests/test_document_category_mappings.py tests/test_shared_media_document_meanings.py tests/test_native_meeting_fidelity.py tests/test_explorer_material_adapters.py tests/test_explorer_house_actions.py tests/test_house_explorer_evidence.py tests/test_congress_api_imports.py tests/test_congress_api_boundaries.py tests/test_document_kind_fallback.py tests/test_document_metadata_preservation.py packages/house-naming/tests/test_document_families.py packages/house-naming/tests/test_document_categories.py packages/house-naming/tests/test_category_wording.py packages/house-naming/tests/test_native_publisher_kinds.py => 490 passed in 6.82s. git diff --check passed. No acquisition, catalog rebuild, classification/review run, workflow/resource change or retained-data mutation. Concrete simplification: House/Senate document policy no longer depends on meeting-record adaptation. Remains in_progress for independent review and parent merge.

**2026-10-19T15:52:00Z**

Independent root review approved implementation 4e947a5. Original b191fc8 source independently matches every frozen mapping set, all alias outputs and category function AST. 490 focused regressions passed. Implementation complete; parent ct-snh8 tracks CI, merge and cleanup.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch czsd).
- Grades: proposal 88 → 85, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
