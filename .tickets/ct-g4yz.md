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

PR173 and PR174 are merged with passing CI. The complete H.R.4307 bill and 210 additional legislative-wrapper pairs are now actually appended and selected in independently reviewed accepted-set-v6. Native checks select all changed keys, suppress old reading controls and reject a wrong digest. Independent raw-source/intermediary/output reading covers the declared example/control scope, with the remaining sources explicitly unreviewed. Fifteen fallback bodies retain original readings and reviewed publication roles; all thirteen linked PDFs remain selected and exposed. The tested explicit wrapper-exclusion helper awaits merge under ct-en4n; that is the remaining integration step before closing this ticket.

Original affected html_text version f1cefe442182dc8e4c456359aebdb37e5c50db6b0abb669b303e05763feb94a3; text SHA 0e0610a6d7eebd908f6cce52923298cb8b9f5f06e9586262ab01607ad142d299. Raw source and output were genuinely read at the member selector and bill heading. Evidence: repairs/corpus-assessment-20261113/triage-current-20261114/markup-exposed8-review-packets-20261115/a6fb358f8a7c/. Historical intermediary unavailable. This one source confirms the mechanism, not corpus-wide scope.

Closed ct-c5xf/ct-082q cover RDFa/main-content metadata and closed ct-chc4 removes scripts/styles. Their evidence is reusable; none establishes that unmarked Congress.gov body_text omits quick-search controls.

## Design

Reuse maintained spicy-docs content/selection capabilities and the existing CT main-content path before adding a reader. Use an exact publisher/structure predicate and preserve a safe explicit fallback when document content cannot be located. Keep genuine legislative forms, tables, testimony and short text; do not globally delete all form or select content without qualification. Measure affected actual keys and prioritize selected/release-exposed text, keeping unassociated corpus items visible. Reparse only the qualified affected HTML set with actual declared versions; retain old readings and source bytes. No OCR or publisher refetch is required.

## Acceptance Criteria

1. Read the exact raw source, actual new intermediary and final output for a6fb358f8a7c and a small appropriate control set; retain the complete bill text while removing unrelated quick-search member options.
2. Demonstrate ordinary hearing preformatted text, legitimate form content, short amendments and missing-selector fallback remain useful; a planted dropped substantive passage fails.
3. Retain exact source/selector/policy/reading/text identities, disclose historical intermediaries that are unavailable, and measure the bounded candidate plus affected-key inventory before selective replay.
4. Qualify the changed behavior with independent raw-source, actual-intermediary and final-output reading of appropriate examples and controls. Adopt the exact validated affected keys through maintained selection, disclose unreviewed source scopes, and preserve unaffected keys/refusal history. The user's FTS goal does not require manual reading of every document or whole-corpus OCR.


## Notes

**2026-11-15T07:05:12Z**

PR173 merged 5cd761d740454469dc5f47263e6a79275cc2a623 with both CI workflows successful. Its actual 4,370-byte bill is selected in independently reviewed v5. PR174 https://github.com/civictechdc/congressional-tech/pull/174 at d44015519ab5bfb939dc5b83f8bb47a23a9f8e62 has 26 focused tests/doctor passed; MCP CI passed and Explorer CI remains live. The 210 new wrapper pairs passed independent all-field candidate/native-stage checks; batch append is queued behind the live OCR body lock. Source review scope is bounded and explicit, not all 210 documents manually read.

**2026-11-15T07:24:33Z**

Accepted-set-v6 is independently qualified: selection SHA 95fad5e005670ce150ce4d09321ff9e321f11fdfa9abd641970c8e63b037c72f; independent result SHA dbd3e66bcd9d8e66142f318e501108db20976557c02e13c254dc349dd17ef539. Evidence: repairs/accepted-text-adoption-20261114/accepted-set-v6-independent-review/. The 210 actual appended pairs are selected; fifteen exact source roles exclude seven exposed viewers while preserving thirteen linked PDFs and the alternate resolution. Main heads: body_text 4020361685539847953; readings 6816097245686786721. PR174 merged at 8965dc00e409dbdbdc6ee4e00af7418a4fc87e59 with both CI workflows successful. Wrapper helper code merge and final handoff remain separate.
