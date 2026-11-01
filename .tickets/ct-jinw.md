---
id: ct-jinw
status: closed
deps: []
links: [ct-h1nd]
created: 2026-10-30T18:34:42Z
type: feature
priority: 2
assignee: mikewolfd
tags: [parsers, pdf-text, refspec]
---
# Add standalone fold_pdf_text helper for PDF presentation ligatures and Unicode hyphens

PDF text extracted via `pdftotext` retains Unicode FB00–FB06 typographic presentation ligatures (`ﬀ`, `ﬁ`, `ﬂ`, `ﬃ`, `ﬄ`, `ﬅ`, `ﬆ`) and U+2010/U+2011 hyphens (`‐`, `‑`), which cause downstream bill-designator, date, and identifier regexes to miss words like `'first'`, `'official'`, `'floating'`, or hyphenated identifiers. Full NFKC normalization is unsafe on legal/congressional text because it mutates fractions (`½` -> `1⁄2`), superscripts (`²` -> `2`), and legal symbols, and generic `parsers/text.py` normalization collapses `\u2014` em-dashes (which `parsers/gpo.py` relies on as `DOCUMENT_NUMBER_DELIMITER`).

Per `DATA-MODEL` §6.6, the `pdf_text` lake table is currently deferred (`--include-pdf-text` off in normal runs) and stores raw per-page `pdftotext` output, while Phase 1 `retention/pdf_tools.py` (`opening_page_text`) feeds `readings` across 155,709 PDFs and must not be invalidated. This ticket provides `fold_pdf_text` as a standalone pure helper ready for downstream text consumers and opt-in PDF text workflows without triggering a Phase 1 `readings` rebuild.

## Design

Owner: `packages/congress_api/src/congress_api/parsers/text.py` (and re-exported from `packages/congress_api/src/congress_api/lake/pdf_text.py`).

1. Port the pure-Python `fold_pdf_text(text: str) -> str` translation table from `RefSpec` (`src/refspec/pdf_text.py`, ~40 lines):
   - Map U+FB00..U+FB06 ligatures to ASCII (`'ff'`, `'fi'`, `'fl'`, `'ffi'`, `'ffl'`, `'st'`, `'st'`).
   - Map U+2010 (`HYPHEN`) and U+2011 (`NON-BREAKING HYPHEN`) to U+002D (`'-'`).
   - Preserve em-dashes (`\u2014`), en-dashes (`\u2013`), fractions (`½`), superscripts (`²`), section symbols (`§`), and all other characters untouched.
2. Do **not** wire `fold_pdf_text` into `retention/pdf_tools.py:opening_page_text()` (preserving Phase 1 `readings` version stability) or mutate raw `pdf_text.pages` unless explicitly requested by a downstream consumer.

## Acceptance Criteria

- `fold_pdf_text` folds all seven U+FB00–U+FB06 ligatures and U+2010/U+2011 hyphens to ASCII equivalents while preserving em-dashes (`\u2014`), fractions (`½`), superscripts (`²`), and section symbols (`§`).
- Phase 1 `readings.current_version("pdf")` and `retention/pdf_tools.py` are unchanged.
- Unit tests cover ligature folding, hyphen folding, and non-destructive preservation of em-dashes, legal symbols, and fractions.

## Notes

**2026-11-01T03:09:00Z**

Implemented fold_pdf_text in packages/congress_api/src/congress_api/parsers/text.py (and re-exported in packages/congress_api/src/congress_api/lake/pdf_text.py) folding U+FB00-U+FB06 ligatures and U+2010/U+2011 hyphens to ASCII while preserving em-dashes, en-dashes, fractions, superscripts, legal symbols, and readings.current_version('sniff'). Verified in packages/congress_api/tests/test_fold_pdf_text.py.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 7d5067b4):
- Verdict: PASS-WITH-CAVEATS (3/3 ACs met; full 1,114,112-codepoint Unicode sweep confirmed only U+2010, U+2011, and U+FB00..U+FB06 change; retention/pdf_tools.py and readings.current_version('pdf') untouched; 45/45 tests pass).
- Remaining work before closure:
  1. [Priority 2] Move `fold_pdf_text` and `_PDF_TEXT_FOLD_TABLE` from `packages/congress_api/src/congress_api/parsers/text.py` into `packages/congress_api/src/congress_api/lake/pdf_text.py` (re-exporting in `parsers/text.py` only if needed without changing `appearance_records` source hashes, or removing `parsers/text.py` from `appearance_records` if unused, so `fold_pdf_text` edits do not churn `appearance_records` `house_xml` and `senate_page` versions).
  2. Fix stale closing-note reference (`readings.current_version('pdf')` rather than `'sniff'`) and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 2 Engineer (b009d889, 100% confidence) across Round 1 & Round 2:
  1. Defined `_PDF_TEXT_FOLD_TABLE` and `fold_pdf_text` in `packages/congress_api/src/congress_api/parsers/text.py:19-40` and re-exported them in `packages/congress_api/src/congress_api/lake/pdf_text.py:1-5` (`lake -> parsers`), obeying `pyproject.toml` layer fences with zero exemptions.
  2. Scoped `appearance_records.py:233,248` to `source_ast_digest(pkg_dir / "parsers/text.py", ("text",))` so `fold_pdf_text` edits never churn `appearance_records.current_versions()`, while keeping `retention/pdf_tools.py` byte-identical to `HEAD` (`00b12db7...`).
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (100%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (100%).
