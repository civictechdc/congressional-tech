# Accepted Body-Text Selection Set v13 — Qualification & Provenance Report

- **Prior Baseline**: `accepted-set-v12` (`model/jobs/inputs/body-text-selection-v12/selection.json.gz`, sha256 `c270fe1bfa190976511f9077d9ae9b1bb45cea9c44f78ae6567564cff64fa91b`, `22,921` overrides, `416` `excluded_bodies`)
- **Total Explicit Overrides**: `22,918` (`v12` had `22,921`; reverted `3` `main_landmark` HTML overrides where landmark scoping truncated real prose)
  - Reverted `html_text` (`fe2a39f4f194a8888d38b1e07354f169f80fbed1e36156960a998640628044d7`) overrides (`ct-m704`):
    1. `9d3094e1f7f54a147d4f9da1b3adbc5b1663b7618f0f4d6d4b5a898450e346a7` (Nicaragua open letter and 801 signers in sibling sections outside `role="main"`, `68,640` B default vs `202` B cleaned)
    2. `653afe17debd09439793c2472faa1035f771dd2e45a02b98ccd5fdd22f5e7592` (Senate Commerce nomination hearing details in `<header>` outside `<main>`, `2,265` B default vs `188` B cleaned)
    3. `9b166e1e24e5999d4166f4f0ec130c3fc4f3fc6b946b10f17a17a391897f457f` (Senate Banking hearing witness list inside `role="main"` within a `display:none` container, `4,057` B default vs `266` B cleaned)
  - Retained `html_cms` (`fe2a39f4f194a8888d38b1e07354f169f80fbed1e36156960a998640628044d7`): `12,768` HTML bodies (`0 / 46` content losses in regular-interval `10–50%` sample audit `.cache/archive-release/ct-m704-v13-20261120/SAMPLE-READ-46.md`; `98 / 101` `<10%` shrinkages verified as legitimate navigation/chrome removal).
  - Retained `warc_compose` (`fb801220a579f726ed152b0565a910421961c18a9ea3048e0801f085b7f0b05a`): `8,505` verified `1:1` `(receipt_key, receipt_line)` `capture_evidence` sibling payload compositions (`http_status=200, complete=True`).
  - Retained `pdf_repairs` and prior `v11` overrides: `1,645` bodies unchanged.
- **Total Excluded Bodies (`excluded_bodies`)**: `416` (unchanged from `v12`).
- **Cleaner Guard & Limits**:
  - `congressional-cms-main-content/002` (`HTML_CMS_CONTENT_SELECTION_VERSION = b06d356ad5e3030f93ec02462f0c2f9a24172608ed39d1adfc506546d0e4e33d`) falls back to ordinary `html_text` when cleaned output is `<500` UTF-8 bytes and `<10%` of a `>=2,000`-byte default (empirical guard fitted to the 3 observed cases above).
  - Plain-language consumer limits accompany this selection in `LIMITS.md`.

## Inherited Source Qualification Pins (`v12`)

- **`html_review`**: `review.md` sha256 `d39886e63e4c362009708438955da6958a4700ea0bb3ce3dc396429283d09ca5` (`5,557` B); `pins.json` sha256 `97282e92250157489149829cad6d30ec781b792f12b4c83d61f1606b399e940c` (`38,036` B)
- **`pdf_review`**: `review.md` sha256 `0ca9341bf15f5e9f9f68e95bde4edc54dacce15ef710ecb457a973ea85ce19b4` (`7,685` B); `pins.json` sha256 `109def0b3c47122a72b85ff430e8ee0447db2f86a29d1d809f64eceb8ca150c2` (`23,607` B)
- **`warc_review`**: `review.md` sha256 `c6062fa7eae86348b30b61cc8420c2e8de2e99fe1c1327c704d823fdd4ee30c6` (`3,827` B); `pins.json` sha256 `5417d9152ddf2a7900f1a658970307ac0120346b5cb026492811397e5d1a9b38` (`34,108` B)
- **`sample_46_10_to_50pct`**: `.cache/archive-release/ct-m704-v13-20261120/SAMPLE-READ-46.md` (`0 / 46` content losses).
