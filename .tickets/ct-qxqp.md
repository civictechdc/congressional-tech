---
id: ct-qxqp
status: closed
deps: []
links: []
created: 2026-10-20T16:51:18Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, identity, linking]
---
# Preserve surface lengths under casefolding and enforce word boundaries in link_mentions

identity/linking.py:27-50, 70-76 pre-casefolds candidate surfaces in _candidate_surfaces and passes surface_folded as needle to _find_occurrences(haystack, needle), which sets length = len(needle) (the casefolded length). When an entity name or alias changes code-point length under .casefold() (such as German 'ß' -> 'ss' in 'Max Weiß' or Turkish 'İ'), _find_occurrences slices the wrong length from haystack and fails to match or shifts span offsets. In addition, _find_occurrences performs an unanchored substring scan with no word boundaries, matching 'Robin Roe' inside 'Robin Roebuck' and 'A. Doe' inside 'M.A. Doering'.

## Design

1. Keep original candidate surface lengths (or group candidate surfaces by both casefolded form and possible code-point window lengths / scan tokens) so haystack[start:end].casefold() == needle_folded is evaluated over the true code-point span in haystack.
2. Enforce non-alphanumeric word boundaries at span start and end when the surface begins or ends with an alphanumeric code point, preventing partial-word prefix/suffix matches while preserving punctuation in initials like 'A. Doe'.

## Acceptance Criteria

- Entities with surfaces whose length changes under .casefold() (e.g., 'Max Weiß' matching 'Max Weiß', 'MAX WEISS', or 'Max Weiss') produce exact code-point spans where haystack[start:end] equals the surface in the version text.
- 'Robin Roe' does not match inside 'Robin Roebuck' and 'A. Doe' does not match inside 'M.A. Doering', while 'A. Doe' and 'José Ríos' still match at punctuation and whitespace boundaries.
- Every emitted mention passes check_corpus span bounds and surface equality checks.


## Notes

**2026-10-20T17:18:34Z**

Casefold-safe code-point span matching with Unicode word boundaries; span dedup and exact matched-surface aggregation. Part of the 27 passing identity tests.

**2026-10-20T17:30:45Z**

Casefold-safe code-point span matching (including length-changing casefolds) and Unicode word-boundary checks; spans deduplicated and aggregated by exact matched surface. Identity tests: 27 passed.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 86 → 86, work 83 → 83.
- Problem: Scaling: for each version, every candidate surface is scanned across the whole text character by character (linking.py:95-107, 63-76).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:53
- Area owner: WS8 (ct-d8cf); not a named step.
- See docs/reviews/2026-10-24-ticket-audit/README.md
