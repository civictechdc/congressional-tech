# Poppler 26.10.0 reading equivalence (ct-ri0x)

Decision: Poppler 26.10.0 reads the project's PDFs the same as 26.06.0, so the
declared reading versions stay unchanged (`sniff` remains `01bf0900…`). The pin
moves for upkeep, not for a fix.

Sample: 466 distinct local bodies, drawn deterministically by stratum from 2,719
retained or recovered PDF-shaped files. It covers 141 sniff-fallback bodies
(no `%%EOF` in the last 8 KB), 30 encrypted, 50 scanned, 40 large (15 over the 16 MiB reader
limit), 16 headerless or damaged, 10 HTML bodies labeled PDF and ordinary retained
bodies. Both builds ran through the project's own entry points, interleaved per file:
`read_sniff_file`, `check_pdf`, `readable_pdf`, `page_count_file`,
`opening_page_text[_file]` pages 1–2, recovery qualification's
`pdfinfo`/`pdftoppm` exits and diagnostics, and the explorer's whole-document
`large_body_reader._poppler` and `pdftotext -q - -` paths.

Result: 0 differences in any reading-feeding field, compared in both
directions. Planted changes (page count, text digest, dropped row) were flagged.
The only difference outside readings is one file's pdfinfo `Title`, which
26.10 decodes further; no reading stores it. No pool file uses `BrotliDecode`,
the stream filter 26.10 adds. Per-file time rose from 0.33 s to 0.39 s for all
nine calls. That increase comes from process start-up in Homebrew's dynamically
linked build: `pdfinfo -v` takes 8 ms with 26.06 and 14 ms with Homebrew 26.10.

Limits: local bodies only (no R2 read); the result covers only the sampled
bodies; rendered pixels were not compared. CI builds 26.10 from source with
Brotli (matching Homebrew) and without HarfBuzz, which only subsets fonts on write.

Evidence: `<main checkout>/.cache/archive-release/investigations/poppler-26.10-20261108/`
(README, per-file results for both builds, sample with sha256 and selection
reasons, scripts).
