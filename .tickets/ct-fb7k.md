---
id: ct-fb7k
status: in_progress
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
