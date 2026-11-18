---
id: ct-yy1r
status: open
deps: []
links: []
created: 2026-11-18T15:41:39Z
type: task
priority: 2
assignee: mikewolfd
tags: [readers, dependencies]
---
# Rebuild the pinned spicy-docs wheel from its merged main

CT pins vendor/spicy_docs-0.85.0+cttesseract.20261117, built from commit bfd3c539 on a 17-commit side branch (codex/ct-source-quality-wheel-20261115) that split from spicy-docs at 0.85.0. Until 2026-11-18 that commit existed only on one Mac; it is now on GitHub (mikewolfd/spicy-docs), and spicy-docs' local main and GitHub main were merged there as pull request 34 (main c33121ea).

A survey on 2026-11-18 (.cache/archive-release/reviews/ticket-state-20261118/i-spicy-docs/, Opus agent, files opened and wheel members compared byte for byte) found shared work CT's wheel does not contain:
- Wayback index and replay readers and a Senate fallback (sources/web_archive.py: read_wayback_index, newest_wayback_captures, read_wayback_replay, WaybackFallback; spicy-stack ticket ss-eskm). CT's wheel has only Common Crawl and WARC there. Needed for ct-z4w5 (damaged publisher PDFs).
- The Vision band-edge fix (spicy-docs pull request 31) and the native word-spacing option native_inhibit_spaces (pull request 32). CT re-implements the spacing in parsers/pdf_opt_in.py; delete that copy once the shared one is pinned. Bears on ct-hz8y.
- The error-page fix a648e60d (never call a PDF or binary body a wall). CT already calls assess_response from pull request 33, which is in the wheel.
Nothing shared exists for: a main-content page cleaner, forms or checkboxes or identifiers in OCR, adaptive render resolution for oversized scans (only CT's opt-in code, which nothing runs outside tests), or host aliases.

Do: build one wheel from spicy-docs main plus the Tesseract backport under a new version string (0.85.0+readers.20261114.2 already names another private wheel), with a receipt naming a pushed source commit; repin; follow docs/development.md 'Reading version changes' and the byte-hashed parser rules (a reader in the import closure moves producer identities: equivalence evidence or a deliberate bump, as done for lxml on 2026-11-18). The spicy-docs merge ran 1,538 focused tests but not the OCR, Vision, Tesseract or rendering tests: run those before building.

## Acceptance Criteria

CT's pinned wheel is rebuildable from a pushed spicy-docs commit on its main; the Wayback readers are importable in CT; CT's own spacing copy is gone; reader equivalence is recorded.

