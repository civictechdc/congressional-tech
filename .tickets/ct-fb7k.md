---
id: ct-fb7k
status: open
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

