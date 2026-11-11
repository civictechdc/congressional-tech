---
id: ct-n3ik
status: open
deps: []
links: []
created: 2026-11-11T15:40:45Z
type: feature
priority: 2
assignee: mikewolfd
tags: [ocr, pdf_text, readings, tesseract]
---
# Hybrid PDF OCR: count typeset versus scanned OCR pages, then re-read typeset pages with Tesseract

Owner decisions 2026-11-11 (session congress-1, questions dialog): 'Hybrid: measure the split first' and, for the spicy-docs Tesseract backend, 'Default to fast'. Evidence: the Vision document-recognition trial (.cache/archive-release/investigations/vision-documents-trial-20261111/README.md) and the Tesseract backend measurement (.cache/archive-release/investigations/tesseract-backend-20261111/). Apple Vision (today: accurate, en-US, correction off, 200 dpi, 3 bands) is better on scanned pages (words recovered 0.966 vs Tesseract fast 0.924 on 35 scans scored against publisher text layers), while on born-digital typeset pages whose text layer is missing or garbled Tesseract fast recovers far more (0.950 vs 0.803 of words on 70 pages; 107 vs 672 of 2,757 lines dropped); every Apple reader drops whole lines of crisp tight type. Vision's new RecognizeDocumentsRequest was trialled and rejected (worse on scans, 35 of 300 flagged pages garbled, 1.28x time, re-read 50-85 h). The three bands help on some flagged pages and lose real text on others (27 vs 42 of 300 by at least 25%). Plan: let the running Vision pass finish; classify every OCR'd page as typeset or scanned with a cheap per-page test (image coverage, fonts, text-layer presence) and count; bring the owner the re-read cost; if adopted, a second pdf_text reading version naming Tesseract (fast, pinned model SHA-256, libtesseract version, PSM, LSTM) for typeset pages, Vision stays for scans; the export prefers by page class. Also covers the earlier decision 'Only where Vision is unavailable' (Linux hosts read with Tesseract).

## Acceptance Criteria

The typeset/scanned split is counted over all OCR'd pages with the classifier's precision checked on a hand-read sample; the owner decides on the re-read with its measured cost; if adopted, typeset pages carry Tesseract readings under their own version, scans keep Vision, and a raw check against native text layers where they exist shows the gain.

