---
id: ct-0hay
status: open
deps: []
links: [ct-m878, ct-jnjv, ct-m704, ct-chc4]
created: 2026-11-09T23:15:13Z
type: bug
priority: 2
assignee: mikewolfd
tags: [congress_api, body_text, warc, export]
---
# WARC-recovered text never reaches the body_text export: rows are keyed by the envelope body

body_text reads a WARC capture by unwrapping it and keys the text row by the WARC envelope's own SHA (parser `warc`). The export (`viewer_publication/body_text_export.py`) ships only rows whose `body_sha` is a `detail.saved_body`. A WARC envelope has record role `envelope`, which is never a saved file, so none of these rows can match. On the 1/16 slice all 96 WARC text rows are outside the export, while the export pointer still counts them under `warc_unwrapped` (.cache/archive-release/body-text-slice-20261109).

To settle first: for a document recovered from a WARC, which body does `detail.saved_body` name (the envelope, or the unwrapped payload), and does a text row exist under that SHA? Then either key the text by the unwrapped payload's SHA, or have the export join through the envelope-to-payload mapping the model already holds. One read per body either way; do not unwrap twice.

## Acceptance Criteria

- Every WARC-recovered document whose payload has text gets it in the export, or the count that cannot is named with reasons.
- The pointer's `warc_unwrapped` count equals rows actually exported.
- Slice re-measure: 96 WARC rows accounted for.


## Notes

**2026-11-10T00:01:58Z**

2026-11-10 settled from the 1/16 slice and release-prep detail.parquet (read-only): detail.saved_body never names a WARC envelope (0 of 96 slice envelope SHAs). Recovered documents (saved_kind=recovery, 6,359 docs, 6,102 bodies) are saved under their own body SHA and already get text under it: 376 of the 391 in the slice have a row (pdf_text 285, html_text 70, xml_text 21; 15 have none, not yet explained). So recovery text is NOT missing from the export. The 96 warc rows are a different population: web-page payloads read out of envelopes; only 9 share exact text with a saved original HTML body. Open question narrowed to: which list rows do those 96 envelopes belong to, and is their payload wanted as document text at all. If not, drop 'warc' from FORMAT_PARSERS (saves the reads) and remove warc_unwrapped from the pointer.

**2026-11-10T03:26:46Z**

2026-11-10 (read-only, slice + release-prep model output): the 96 slice WARC envelopes are provider responses (family external/provider-responses, application/warc+gzip) for 94 veterans.house.gov testimony and opening-statement pages plus one edlabor.house.gov and one doyle.house.gov page. 95 of the 96 URLs are published documents and every one has saved_body = a separate text/html body (saved_kind original), never the envelope. 9 of those saved bodies fall in the slice prefix and all 9 have an html_text row whose text is identical to the envelope's warc row. So the envelope row duplicates text the document gets under its own saved body once html runs on every prefix. Not yet shown corpus-wide (1,768 warc bodies by sniff). Plan: read html and warc together in the html phase of the full run, compare every envelope's payload text with the html_text row of the saved body at the same URL; if all match, drop warc from FORMAT_PARSERS and warc_unwrapped from the pointer; if some envelopes have no saved body with text, name them and key those rows by the payload.
