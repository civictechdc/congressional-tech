---
id: ct-jinw
status: open
deps: []
links: []
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
