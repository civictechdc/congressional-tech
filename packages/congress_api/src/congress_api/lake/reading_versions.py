"""Declared meanings of reading rows and combined unreadable decisions."""
READING_VERSIONS = {
    'sniff': '01bf09000fce8229a468583c23f869fc639c56e3e87a1ca447dd66c5f99bff6b',
    'html': '61d7904883f042f48d3732d0518adaa5cf5084790ebc9d5411aad7a6ab605969',
    'xml': 'c9d955b28b401a3fe56386a4a221b3f2147baa0f1da503c7c6a224f4808d085f',
    'json': 'f8d98b4305d8b85bdb6323b91ca56c9c01e0ffd3234ed89d9d90afadc37cae93',
    'html_metadata': '0fff8151c7752109cc3778d9570e682985edce2e1f90e04c3b638c37a6c4a129',
    'readings': '7b006df14ea065d7bab8c15a319c9201c57d4547c174d722651a33107dbd73ed',
    # Body-text parsers (data model §6.6), declared 2026-11-08: each ID is the SHA-256 of its
    # declaration below, computed once and never recomputed; warc's names the IDs it routes to.
    # html_text and warc were redeclared 2026-11-10 for the spicy-docs 0.84.0 htm rule (ct-chc4).
    # pdf_text changes for the GPO repair; html_text/xml_text and composed warc change for
    # qualified markup normalization. The markup candidate keeps the PDF declaration unchanged.
    # PyMuPDF, spicy-docs and the macOS build are drift evidence in
    # model/reading-version-diagnostics.json, never inputs.
    'pdf_text': '4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8',
    'html_text': 'd94ae28a12425256aeec1cf1200f761d803d80f4e7762b9b80abfa0b675d516c',
    'xml_text': '98efdf43b03ff4d157daef312658428fc10193643bd704d91d90c908df2b8714',
    'warc': 'f2b98658b8888692ba56ae0525715a9906ae73e59611b87f612cc1f66301e0ce',
}

# What each body-text ID declares. A change to what one of these says is a new ID.
BODY_TEXT_DECLARATIONS = {
    'pdf_text': ('body_text pdf_text 2026-11-13: spicy-docs body_text pdf derivation 004+gpo.20261113 '
                 '(DocumentExtractor, normalize_gpo_pages, pages joined by one newline); printing continuation '
                 'ends at the first unknown line; prose bullets survive; whole bill/stage footer labels require '
                 'printing or numbered-layout evidence; page rule spicy-docs NativeOrOcr over each '
                 "page's native text as normalize_gpo_pages leaves it, the page alone: recognize a page whole when "
                 'it has no text layer, when its normalized text carries a control character other than tab and '
                 'line breaks or U+FFFD, or when it has under 50 non-whitespace characters and draws an image; OCR '
                 'by Apple Vision, accurate, language correction off, in 3 horizontal bands, raw RGB at 200 dpi; '
                 'failed pages make an error with no text; 64 MiB stored bound'),
    'html_text': (('body_text html_text 2026-11-13: spicy-docs body_text htm derivation 005+ctmarkup.20261113; '
                  'UTF-8 HTML with title, script, style, noscript and template content dropped; ordinary HTML '
                  'whitespace collapses across text events with block breaks, navigation labels and buttons '
                  'separated, partial-word prose anchors kept; pre layout preserved locally and pure pre bodies '
                  'keep their original layout; hidden pre tags do not affect visible prose; print EOF markers do '
                  'not consume block breaks; event bound limits nesting; one page; 64 MiB stored bound')),
    'xml_text': (('body_text xml_text 2026-11-13: spicy-docs body_text xml derivation 005+ctmarkup.20261113; '
                  'generic XML keeps element boundaries as line breaks and whitespace-only lines dropped, '
                  'including metadata; native bill root with Congressional bill DTD public identifier and GPO USLM '
                  'namespace qualify legislative normalization: remove bibliographic metadata, collapse formatting '
                  'whitespace and preserve known inline citations; resolve namespaces per element, retain '
                  'conservative boundaries for foreign and unknown fields; one page; 64 MiB stored bound')),
    'warc': (('body_text warc 2026-11-13: spicy-docs read_warc_response (one response record, payload SHA-1 '
                  'checked), HTTP gzip/deflate content encoding decoded within 64 MiB, payload sniffed and read by '
                  'pdf_text 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8, html_text '
                  'd94ae28a12425256aeec1cf1200f761d803d80f4e7762b9b80abfa0b675d516c or xml_text '
                  '98efdf43b03ff4d157daef312658428fc10193643bd704d91d90c908df2b8714')),
}

# Preserve the existing bundle ID for the exact migration leaf IDs and policy.
MIGRATION_BUNDLE_INPUTS = 'eb1390f56e0216d7ed9ea94db85264a51a2dfd63c1831bc87e2f25c25683bf04'
