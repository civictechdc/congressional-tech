# Accepted Body-Text Selection Set v12 — Qualification & Provenance Report

- **Release Target**: `55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105`
- **Prior Baseline**: `accepted-set-v11` (`body_text` snapshot `3111718351420837925`, `readings` snapshot `81858754778267610`)
- **Appended Catalog Snapshots**: `body_text` `401430595319522981`, `readings` `616652117714703268`
- **Total Explicit Overrides**: `22,921` (`v11` had `1,606`; net new/updated in `v12`: `21,315`)
  - `html_cms` (`fe2a39f4f194a8888d38b1e07354f169f80fbed1e36156960a998640628044d7`): `12,771` direct + payload HTML bodies stripped of CMS `<nav>`/header/footer/sidebar and retroactive `"119th Congress"` banners while preserving `<pre>` transcripts and inline tails.
  - `warc_compose` (`fb801220a579f726ed152b0565a910421961c18a9ea3048e0801f085b7f0b05a`): `8,505` verified `1:1` `(receipt_key, receipt_line)` `capture_evidence` sibling payload compositions (`http_status=200, complete=True`).
  - `pdf_repairs` (`5d84e2bca02998e7b509ec12d2b5c17ef12d9da8a76c3e4b8e1f487b6f7c8f82`, `b345ac1cf8f88e2726a5de04cd92d470c3d83fbf490e9724b308797c6901a0f9`, `4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8`): `39` PDF bodies (selective Tesseract 5.5.4 replacement on held 1,208-page report `251ea1a6...`, bounded CPU Tesseract on `memory17` oversized/rotated scans, GPO cleanup-loss renormalizations, and `native_inhibit_spaces` repairs).
- **Total Excluded Bodies (`excluded_bodies`)**: `416` (`v11` had `26`; added `390` confirmed `NoSuchKey`, `Meeting Not Found`, `File Not Found`, `natural_resources_not_found`, site technical-difficulties, and error-payload WARC envelopes).

## Manual Hydrogen (`gemini-4-hydrogen-medium`) Source Qualification Pins

- **`html_review`**: `review.md` sha256 `d39886e63e4c362009708438955da6958a4700ea0bb3ce3dc396429283d09ca5` (`5,557` B); `pins.json` sha256 `97282e92250157489149829cad6d30ec781b792f12b4c83d61f1606b399e940c` (`38,036` B)
- **`pdf_review`**: `review.md` sha256 `0ca9341bf15f5e9f9f68e95bde4edc54dacce15ef710ecb457a973ea85ce19b4` (`7,685` B); `pins.json` sha256 `109def0b3c47122a72b85ff430e8ee0447db2f86a29d1d809f64eceb8ca150c2` (`23,607` B)
- **`warc_review`**: `review.md` sha256 `c6062fa7eae86348b30b61cc8420c2e8de2e99fe1c1327c704d823fdd4ee30c6` (`3,827` B); `pins.json` sha256 `5417d9152ddf2a7900f1a658970307ac0120346b5cb026492811397e5d1a9b38` (`34,108` B)

## Scope & Explicit Non-Claims

- Default `pdf_text`, `html_text`, `xml_text`, and `warc` declarations and fixed reader-fixture digests are unchanged; repaired and composed cohorts bind explicit `parser_version` identities.
- Cold-R2 sidecar excerpts (`cold_r2_hydrated_bodies_v6_1.parquet`, capped at 8,000 chars) are NOT imported into `body_text` as full documents; only verified full-document readings with SHA-256 provenance enter `body_text`.
- Unreviewed baseline bodies retain their historical readings without restamping.
