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

