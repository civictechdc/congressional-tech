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


## Notes

**2026-11-10T00:33:12Z**

2026-11-10 from the spicy-stack session (ss-uxon, branch claude/ss-uxon-html-nontext d37f71a3 fix + 4eeb94e9 release 0.84.0, local, full gate running, not yet reviewed): htm now drops script, style, noscript and template content. Measured no text change for xml, uslm, txt and pdf (208/4/21/121 bodies, 0 changed). CT re-read scope is html_text AND warc: reading_versions.py declares warc by the IDs it routes to, and all 96 slice warc readings have an html payload carrying script or CSS. xml_text and pdf_text stay. After the re-read, list bodies whose new text is far shorter than the old (an unclosed script/style element drops the rest of the document; 0 of 1,600 sampled bodies had one; 10 challenge-style pages became near-empty).

**2026-11-10T01:01:41Z**

2026-11-10 converter comparison (owner asked whether to use a mainstream HTML-to-Markdown converter). 400 scored pages from the slice, all bodies hash-checked; README and tables in .cache/archive-release/investigations/html-text-converters-20261110/. Decision: keep the spicy-docs reader with the script/style fix as html_text. trafilatura 2.0.0 cuts committee-page boilerplate from about 30% to 8-12% but drops a date, link label or table cell on 22 of 79 hearing pages (a witness name among them), rewrites all 68 GovInfo <pre> documents and returns nothing for 13; 200 of 383 texts differ between 2.0.0 and 2.3.1. markdownify 1.2.3 keeps the same menus and footers as the reader. The fix removes script text on 288 of 288 affected pages with no words lost and <pre> documents byte-identical (emulated arm). One reader defect found: no break between block elements glues words on 86 of 258 non-<pre> pages; asked spicy-stack to ship that with or right after 0.84.0. CT bumps html_text and re-reads html and warc once, on the release that has both fixes (12,032 slice bodies, about 192k at full scale, no OCR). The slice was read with spicy-docs 0.79.0+body.text.f20f38dc. Not measured: boilerplate on hosts with fewer than 5 sampled pages; word order (loss is a bag of words).
