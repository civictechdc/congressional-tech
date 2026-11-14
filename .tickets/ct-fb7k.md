---
id: ct-fb7k
status: closed
deps: []
links: [ct-f6hr, ct-n3ik]
created: 2026-11-14T12:27:35Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-en4n
tags: [body_text, quality, html, xml, fts, response_detection]
---
# Detect House meeting and file error pages from retained examples

The maintained response-role reader recognizes storage NoSuchKey responses but does not recognize the House Meeting Not Found and File Not Found templates. The retained example inventory contains 197 storage errors, 173 meeting errors and 14 file errors; all extracted successfully, so completion alone cannot identify the source problem. Two of the other 16 bodies are directly reviewed ordinary metadata/landing controls and 14 remain unassessed.

This is the bounded detector implementation slice of ct-en4n. That parent retains broader source-role and capture-history qualification. Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/response-examples-20261114/ and repairs/markup-reparse-20261114/held-current-version/source-review.md.

## Design

Extend congress_api.parsers.response_roles.assess_response and its existing text-quality consumer. Reuse spicy-docs markup events, bounded original-byte evidence and the existing policy version mechanism. Match the reviewed House structure and combined diagnostics; generic words, title presence and short text are not sufficient. Keep extraction status, response role and accepted selection separate. Preserve every original, diagnostic and unknown label. This work does not select document text, restart OCR or refetch publishers.

## Acceptance Criteria

1. Recognize both House response templates through the actual response-role and quality-measurement consumers; retain the existing storage-error behavior and explicit reasons/evidence.
2. Replay the retained examples from exact archived source identities and report expected matches, misses, false positives and unread inputs. Treat the 384 instances as three template families; the 14 unassessed records have no forced good/bad expectation.
3. Check ordinary meeting metadata/landing pages, substantive documents quoting error phrases, hidden/script text and mixed-content controls. A planted false positive and a missed-template case must be caught.
4. A named independent reviewer directly reads a small raw input -> parsed evidence -> final observation sample. Preserve review scope and source/output hashes; automated tests supplement this reading.
5. Record time, memory, payload bytes read and policy identity. No per-document LLM calls, OCR, publisher refetch or selected-text changes.


## Notes

**2026-11-14T13:48:31Z**

Implemented the bounded House meeting/file response observations in response_roles, reused by the actual text-quality consumer. Policies move to ct-response-roles-v2 and ct-text-quality-measures-v2; extraction versions, capture/refusal history and selection stay unchanged.

The exact retained 400-key replay read all inputs: 173 House meeting errors, 14 file errors and 197 storage errors matched; both reviewed ordinary controls remained unassessed, as did the 14 records without a good/bad label. The old policy missed all 187 House cases. Planted M005 false-positive and M004 missed-template observations were caught. These are three template families and development controls, not a held-out accuracy estimate.

67 focused tests passed (partial production-offline lane, 2/555 files). Replay: 7,988,904 decoded bytes, 22.97 s, 0.152 GiB peak RSS, normal 6 GiB admission; five originals reused and only exact retained archive keys read. No publisher refetch, OCR/provider job, catalog or selection change.

Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/corpus-assessment-20261113/house-response-detection-20261114/README.md, run-02/summary.json, run-02/outcomes.jsonl, run-02/review-cases.jsonl, and run-02/review-cli/. Raw, parsed evidence and current output locators/hashes are retained for all five representative cases. Awaiting named independent root review and integration; ticket remains in_progress.

**2026-11-14T14:08:02Z**

Independent review at 4e68755b found two concrete false positives: duplicate attributes could supply hidden/ambiguous House evidence, and quoted alert descendants (or an outer q) could supply the complete diagnostic. The repair propagates attribute ambiguity through the primary area, keeps first-value HTML visibility, and disqualifies quoted alert content while preserving the authentic h1/small/blockquote subtitle. It retains the v2 observation policies and all extraction/parser versions.

96 focused tests now pass (partial production-offline lane, 2/555 files), including both House families, duplicate ancestor identity/style, heading/diagnostic descendants, all quoted wrappers, the real subtitle, and downstream FTS non-promotion. Normal 6 GiB watchdog admission; 0.29 GiB peak RSS. Ruff and git diff --check passed for changed code/tests.

The independent old-commit certificate and exact 36 retained controls remain frozen at house-response-detection-20261114/independent-code-review.md and independent-review/. Root directly reviewed the five source -> retained parse/text -> role/CLI paths in root-source-review.md and root-cli-review/. Exact inputs stay unchanged. Repair replay and independent repaired-commit acceptance are next; ticket remains in_progress until handoff.

**2026-11-14T14:12:42Z**

Completed the bounded detector implementation and independent repair acceptance. Exact reviewed code commit: 22fc142916330c82d26e0d8038c495fcdcd7f9bb. Independent repaired-code approval: house-response-detection-20261114/independent-repaired-code-review.md (SHA-256 98b192f9c0e824d722ef23c1e8c68458778debf0a063e357130bb5d406ad90b8). All 36 frozen independent controls pass, including all eight former duplicate/quote false positives and unchanged ten ordinary legacy positives. Root's direct source -> retained parse/text -> role/CLI review is root-source-review.md, with root-cli-review/ actual outputs.

96 focused tests passed (partial production-offline, 2/555 files; not a full lane), plus Ruff/diff checks. Exact-commit local replay in repair-02/ preserves all 400 role/reason/evidence records: 384 known response matches, zero known misses, zero false positives among two reviewed ordinary controls, 14 unlabelled unknowns. Actual five-case CLI measurements are byte-identical to root's; proposals differ only in the newly written evidence path and derived assessment ID, which the maintained consumer reproduces. First strict comparison refusal remains preserved under repair-01/ and repair-replay.log.

Successful replay: 7,988,904 raw bytes plus 132,307 raw and 2,584 retained-text bytes for the five CLI cases; 1.929 seconds, 0.12 GiB RSS, normal 6 GiB admission. No source request, OCR/provider, extraction-version, capture/refusal, catalog or selected-text change. Detailed repair receipt: house-response-detection-20261114/repair-review.md and repair-02/summary.json. This closes ct-fb7k's implementation/consumer-review slice; parent ct-en4n retains broader corpus/source-history work. Root owns integration/CI and any push/merge.
