---
id: ct-yy1r
status: in_progress
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


## Notes

**2026-11-18T20:27:36Z**

2026-11-18 branch value review (.cache/archive-release/reviews/branch-value-20261118/c-sd-wheels/REPORT.md, checked here by content): rebuilding the wheel from spicy-docs main as planned would DROP five fixes that are in the pinned wheel source bfd3c539 and that CT uses (3 files on main reference NativeGeometryError, native_geometry_fallback or declared-or-windows-1252). On fork/main none of _legislative_namespace, _only_preformatted_body, NativeGeometryError, native_geometry_fallback, declared-or-windows-1252 exists. Port these to spicy-docs main first (library code, docs and tests only; not the +gpo/+markup version pins, and not the stale evidence.py docstring): 358a0778 GPO VerDate footer no longer truncates body text and prose bullets are kept; ce38a3db legislative XML normalization only for qualified bill.dtd/USLM XML, local <pre> kept local; d0d929ef (alias 0c8582ec) NativeGeometryError and NativeOrOcr.native_geometry_fallback; d2ad8df3 (alias 2469ce9f) declared-or-windows-1252 HTML decoding wired into rendition_text; b064f96a (alias a756c10d) House amendment-doc XML qualification and punctuation spacing. Every other CT wheel side branch is already on spicy-docs main.

**2026-11-18T22:03:24Z**

2026-11-18 22:00Z: five-fix port on spicy-docs branch port/ct-wheel-fixes-20261118 (worktree /Users/mikewolfd/Work/spicy-stack-worktrees/spicy-docs-port-ct-fixes-20261118), one commit over fork/main c33121ea, NOT pushed. Codex checks 1-4 fixed: txt reuse, squash, punctuation, CRLF, charset forwarding. Check 4 left: line-ending cases (being fixed by normalizing CRLF/CR to LF at the reader) and inverted/infinite PDF boxes labelled zero_area. Next: final Codex check, push to fork, PR on mikewolfd/spicy-docs, OCR and Vision tests before the wheel rebuild. Handoff: .cache/archive-release/reviews/handoffs-20261118/spicy-docs-port.md

**2026-11-18T23:42:03Z**

2026-11-18: Rebuilt reproducible wheel vendor/spicy_docs-0.85.0+ctmain.20261118-py3-none-any.whl (sha256 05ee4864c5227963962be9ef11f376e6a40a8125698df3ca4629f560c29d4f7b, two byte-identical uv build --wheel builds) from spicy-docs branch ct-main-tesseract-20261118 commit 381f17032f805a7e297012033156dbaea6d119be atop five-fix CT reader port cff95c1b40533abc96fd08e66ba6fb73b07cdf65 on merged main c33121ea2d8e4ad1e9e352f1ae213f33f34ea0f3 (upstream Tesseract from c5d5f2ba already AST-identical in extraction/ocr.py; skipped OCR/Vision/Tesseract/rendering/Wayback/error-page suites verified: 1,107 passed in spicy-docs). Repinned CT pyproject.toml, packages/congress_api/pyproject.toml, and uv.lock; verified Wayback readers (read_wayback_index, newest_wayback_captures, read_wayback_replay, WaybackFallback) and error-page PDF guard (a648e60d); deleted CT duplicate _OptInPDFPage.native spacing copy in parsers/pdf_opt_in.py delegating to spicy-docs PR 32 (_PDFPage.native, verified byte-identical across all 5 accepted-set-v12 spacing PDFs); verified zero byte-hashed record/filename producers import spicy_docs; redeclared html_text, xml_text, warc, and HTML/XML opt-in declarations for derivation 006 while retaining pdf_text and house_floor_feed equivalence (11/11 diagnostic fixtures, 411/411 assess_response, f1e2e2 p36 Vision/Tesseract identical; 1,156 passed across 60 CT production-offline reader/version/recovery/export test files). Kept in_progress solely awaiting user approval to push port/ct-wheel-fixes-20261118 and ct-main-tesseract-20261118 to mikewolfd/spicy-docs. Evidence: .cache/archive-release/ct-yy1r-20261118/.
