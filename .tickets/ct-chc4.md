---
id: ct-chc4
status: open
deps: []
links: [ct-0hay, ct-m878, ct-jnjv, ct-m704]
created: 2026-11-09T23:14:53Z
type: bug
priority: 1
assignee: mikewolfd
tags: [congress_api, body_text, spicy-docs, html]
---
# HTML body text keeps script, JSON-LD and CSS: 2,843 of 2,929 exported web-page texts

`html_text` rows come from the shared spicy-docs reader (`parsers/body_text.py::markup_text` -> `spicy_docs.extraction.body_text.rendition_text`). That reader assumes a body has no `<script>` or `<style>` content (spicy-docs `extraction/body_text.py` lines 52-53), which is false for congressional pages: text starts with JSON-LD blobs, inline JavaScript and CSS, then site navigation.

Measured on the 1/16 slice (.cache/archive-release/body-text-slice-20261109): script or CSS content in 6,804 of 12,032 HTML texts, and in 2,843 of the 2,929 that are a document's saved file (the ones the export ships). Example: a Ways and Means opening statement whose text begins with a schema.org `@graph` blob.

The fix belongs in spicy-docs (owned by the spicy sessions; CT does not edit it): drop script, style, noscript and template content before rendering. Then CT bumps the `html_text` reading version and re-reads HTML only (12,032 bodies in the slice, no OCR), which is cheap. Not a blocker for the PDF/OCR full run.

Related, not the same: the model already selects a page's main content (`detail.main_content` / `selected_text`), but only 144 of these 2,939 saved pages have a marked selection (2,788 are `fallback / no_candidate`), so body_text stays the full-page rendition and must be clean on its own.

## Acceptance Criteria

- spicy-docs release that drops script/style/noscript/template content, with a regression fixture from a congressional page.
- CT vendored wheel moved to that release; `html_text` version bumped; HTML-only re-read of the slice.
- Re-measured: saved HTML texts containing script or CSS content is 0 of 2,929 (or each remaining one named).

