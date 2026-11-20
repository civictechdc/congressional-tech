# Accepted Body-Text Selection Set v13 — Consumer Accuracy & Coverage Limits

This file accompanies `selection.json.gz` (`accepted-set-v13`) and the published `derived/body_text/current.json` Parquet export in plain language so downstream search and reading consumers know what is covered and where extraction limits remain.

## 1. Known PDF Extraction & OCR Imperfections

Plain-text extraction and OCR over scanned or degraded Congressional PDFs are usable for full-text search and reading, but carry minor character, form-widget, and layout limits. Concrete reviewed examples in the accepted corpus:

- **Identifier character substitution (`8cecb713...`, page 81):** OCR reads the alphanumeric identifier `011806-29` as `O11806-29` (leading zero read as capital `O`). Exact identifier lookups should account for `0`/`O` and `1`/`I`/`l` OCR confusions on scanned pages.
- **Interactive / flattened form fields (`8ce75966...`):** On witness truth-in-testimony and disclosure forms whose filled values are stored in non-text form widgets, checked boxes, or unflattened annotations, plain-text extraction loses the typed witness name, the checked yes/no answer, and the signature date while keeping the printed form prompt text.
- **Long multi-column / scanned report imperfections (`251ea1a6...`, 1,208-page report):** Selective Tesseract 5.5.4 recovery restores the unreadable pages, but drops a sentence on page 151 and misreads a section heading on page 740. Other reviewed scanned PDFs can omit small map labels, misplace checkbox marks, or linearize multi-column tables out of reading order.

## 2. Cleaned HTML Selection & Empirical Shrinkage Guard (`v13`)

- **Three `v12` `main_landmark` overrides reverted in `v13`:** Independent audit (`ct-m704`) found 3 of the 101 `<10%` `main_landmark` overrides where scoping to `<main>` / `role="main"` dropped real page prose:
  - `9d3094e1f7f54a147d4f9da1b3adbc5b1663b7618f0f4d6d4b5a898450e346a7`: open letter and 801 signers placed in sibling `<section>` elements outside `role="main"` (`68,640` B default vs `202` B cleaned).
  - `653afe17debd09439793c2472faa1035f771dd2e45a02b98ccd5fdd22f5e7592`: Senate Commerce nomination hearing details placed in `<header>` outside `<main>` (`2,265` B default vs `188` B cleaned).
  - `9b166e1e24e5999d4166f4f0ec130c3fc4f3fc6b946b10f17a17a391897f457f`: Senate Banking hearing witness list placed inside `role="main"` within a `display:none` container (`4,057` B default vs `266` B cleaned).
  All three are removed from `v13` `overrides` so publication uses the unpruned HTML reading.
- **Regular-interval `10–50%` sample audit (`46` of `2,643` rows):** Reading every 60th `in_export` HTML override in the `10–50%` retention band against raw HTML (`0 / 46` substantive prose losses; `.cache/archive-release/ct-m704-v13-20261120/SAMPLE-READ-46.md`) confirmed that shrinkage in that band removes site navigation, committee rosters, footers, and retroactive Congress banners while keeping the statement, press release, or bill text. On `rdfa_content_encoded` committee statement pages (such as `veterans.house.gov`), the `content:encoded` body retains the full statement text while omitting outer page-wrapper `<h1>` headings and back-links already carried in `detail.title` and `sources`.
- **Cleaner guard (`congressional-cms-main-content/002`):** CT's HTML cleaner now falls back to ordinary `html_text` whenever the cleaned text is under `500` UTF-8 bytes and under `10%` of an ordinary `html_text` reading of at least `2,000` UTF-8 bytes. This rule is fitted to the three observed cases above — it is a safety guard against extreme landmark truncation, not a formal proof that larger pages can never hide prose outside `<main>` or inside `display:none` tabs.

## 3. Non-Text Formats & Explicit Exclusions

- `416` reviewed `error_response`, `wait_response`, `feed`, and `wrapper` bodies (`excluded_bodies`) are intentionally omitted from `body_text` so HTTP 404/maintenance pages and empty viewer shells never surface as document text.
- Binary office/archive formats (`DOCX`, `DOC`, `ZIP`, images) and unrecovered damaged publisher PDFs (`docs/plans/ocr-source-recovery-inventory.json`) have no row in `derived/body_text/<sha256>.parquet`; `BodyTextSSOT` reports those coverage categories explicitly rather than silently dropping documents.
