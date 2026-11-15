---
id: ct-g4yz
status: in_progress
deps: []
links: [ct-082q, ct-chc4, ct-cbkz, ct-n3ik]
created: 2026-11-15T04:59:35Z
type: bug
priority: 2
assignee: mikewolfd
tags: [body_text, html, source-quality, fts]
---
# Keep Congress.gov quick-search controls out of document text

A direct current-source/output review found Congress.gov quick-search member options in selected document text. Body a6fb358f8a7c567829dafb5493ec352b88cd22a0ce835ec8bbf01237a9b47471 has 53,331 UTF-8 output bytes including unrelated member names from form#quick-search-legislation and select#legislation-representatives; its actual bill text appears only near output character 47,000. The paired XML reading is 4,370 bytes; complete bill equivalence requires direct review. This is search pollution, separate from the harmless letter-spaced enrolled-bill heading that initially triggered review.

Exact current html_text version f1cefe442182dc8e4c456359aebdb37e5c50db6b0abb669b303e05763feb94a3; text SHA 0e0610a6d7eebd908f6cce52923298cb8b9f5f06e9586262ab01607ad142d299. Raw source and output were genuinely read at the member selector and bill heading. Evidence: repairs/corpus-assessment-20261113/triage-current-20261114/markup-exposed8-review-packets-20261115/a6fb358f8a7c/. Historical intermediary unavailable. This one source confirms the mechanism, not corpus-wide scope.

Closed ct-c5xf/ct-082q cover RDFa/main-content metadata and closed ct-chc4 removes scripts/styles. Their evidence is reusable; none establishes that unmarked Congress.gov body_text omits quick-search controls.

## Design

Reuse maintained spicy-docs content/selection capabilities and the existing CT main-content path before adding a reader. Use an exact publisher/structure predicate and preserve a safe explicit fallback when document content cannot be located. Keep genuine legislative forms, tables, testimony and short text; do not globally delete all form or select content without qualification. Measure affected actual keys and prioritize selected/release-exposed text, keeping unassociated corpus items visible. Reparse only the qualified affected HTML set with actual declared versions; retain old readings and source bytes. No OCR or publisher refetch is required.

## Acceptance Criteria

1. Read the exact raw source, actual new intermediary and final output for a6fb358f8a7c and a small appropriate control set; retain the complete bill text while removing unrelated quick-search member options.
2. Demonstrate ordinary hearing preformatted text, legitimate form content, short amendments and missing-selector fallback remain useful; a planted dropped substantive passage fails.
3. Retain exact source/selector/policy/reading/text identities, disclose historical intermediaries that are unavailable, and measure the bounded candidate plus affected-key inventory before selective replay.
4. Adopt only independently source-reviewed changed outputs through maintained selection, preserving unaffected actual keys and refusal history. No whole-corpus OCR or unqualified generic content heuristic.

