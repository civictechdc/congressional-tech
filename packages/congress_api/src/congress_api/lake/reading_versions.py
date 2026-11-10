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
    # PyMuPDF, spicy-docs and the macOS build are drift evidence in
    # model/reading-version-diagnostics.json, never inputs.
    'pdf_text': '2980a4db41cbe1f559532557c5ad59f86691527c2569e8b3746c9d32c6f8fdfd',
    'html_text': 'e1928f25e2803cd6bc8546d1673ff7ba01a11ae861c322165c78af9d32380941',
    'xml_text': 'ed9eb0e2908729e728b02380f50ae994e395a03da5ae50caa21c9e80d378a6db',
    'warc': 'e835fb8116a0ed204706c7cbed136cab4f7e49885e773369c663232672d5e397',
}

# What each body-text ID declares. A change to what one of these says is a new ID.
BODY_TEXT_DECLARATIONS = {
    'pdf_text': ('body_text pdf_text 2026-11-08: spicy-docs body_text pdf derivation (DocumentExtractor, '
                 'normalize_gpo_pages, pages joined by one newline); page rule spicy-docs NativeOrOcr over each '
                 "page's native text as normalize_gpo_pages leaves it, the page alone: recognize a page whole when "
                 'it has no text layer, when its normalized text carries a control character other than tab and '
                 'line breaks or U+FFFD, or when it has under 50 non-whitespace characters and draws an image; OCR '
                 'by Apple Vision, accurate, language correction off, in 3 horizontal bands, raw RGB at 200 dpi; '
                 'failed pages make an error with no text; 64 MiB stored bound'),
    'html_text': ('body_text html_text 2026-11-10: spicy-docs body_text htm markup reader as of 0.84.0, '
                  'derivation 004 (UTF-8 HTML; <title>, <script>, <style>, <noscript> and <template> content '
                  'dropped; one line break where a block-level element or <br> (HTM_BLOCK_ELEMENTS) outside <pre> '
                  'falls between visible text on one line; <pre> layout kept; nesting depth bounded only by the '
                  'event bound); one page; 64 MiB stored bound'),
    'xml_text': ('body_text xml_text 2026-11-08: spicy-docs body_text xml markup reader (element boundaries '
                 'as line breaks, whitespace-only lines dropped); one page; 64 MiB stored bound'),
    'warc': ('body_text warc 2026-11-10: spicy-docs read_warc_response (one response record, payload SHA-1 '
             'checked), HTTP gzip/deflate content encoding decoded within 64 MiB, payload sniffed and read by '
             'pdf_text 2980a4db41cbe1f559532557c5ad59f86691527c2569e8b3746c9d32c6f8fdfd, html_text '
             'e1928f25e2803cd6bc8546d1673ff7ba01a11ae861c322165c78af9d32380941 or xml_text '
             'ed9eb0e2908729e728b02380f50ae994e395a03da5ae50caa21c9e80d378a6db'),
}

# Preserve the existing bundle ID for the exact migration leaf IDs and policy.
MIGRATION_BUNDLE_INPUTS = 'eb1390f56e0216d7ed9ea94db85264a51a2dfd63c1831bc87e2f25c25683bf04'
