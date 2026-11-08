"""Declared meanings of reading rows and combined unreadable decisions."""
READING_VERSIONS = {
    'sniff': '01bf09000fce8229a468583c23f869fc639c56e3e87a1ca447dd66c5f99bff6b',
    'html': '61d7904883f042f48d3732d0518adaa5cf5084790ebc9d5411aad7a6ab605969',
    'xml': 'c9d955b28b401a3fe56386a4a221b3f2147baa0f1da503c7c6a224f4808d085f',
    'json': 'f8d98b4305d8b85bdb6323b91ca56c9c01e0ffd3234ed89d9d90afadc37cae93',
    'html_metadata': '0fff8151c7752109cc3778d9570e682985edce2e1f90e04c3b638c37a6c4a129',
    'readings': '7b006df14ea065d7bab8c15a319c9201c57d4547c174d722651a33107dbd73ed',
    # Body-text parsers (data model §6.6), declared 2026-11-08: each ID is the SHA-256 of its
    # declaration below, computed once and never recomputed. PyMuPDF, spicy-docs and the macOS
    # build are drift evidence in model/reading-version-diagnostics.json, never inputs.
    'pdf_text': 'b01e6b94cd41159b0b1f1de3c3d326f7485f23594337b3b5cad59d0eb2c71b4b',
    'html_text': '00994d3df2a6f0fba27827ed098c7b17204132e45a19c77b1b10260c2321bdf4',
    'xml_text': 'ed9eb0e2908729e728b02380f50ae994e395a03da5ae50caa21c9e80d378a6db',
    'warc': 'cfb84b11b8809305f94bb7306286cc84dd33f2c353910942cc51d17466e81485',
}

# What each body-text ID declares. A change to what one of these says is a new ID.
BODY_TEXT_DECLARATIONS = {
    'pdf_text': ('body_text pdf_text 2026-11-08: spicy-docs body_text pdf derivation (DocumentExtractor at '
                 '200 dpi, normalize_gpo_pages, pages joined by one newline); OCR by Apple Vision, accurate, '
                 'language correction off, 200 dpi, for a page with under 50 non-whitespace native characters '
                 'that draws an image, or with an unmapped-glyph-code line; failed pages make an error with no '
                 'text; 64 MiB stored bound'),
    'html_text': ('body_text html_text 2026-11-08: spicy-docs body_text htm markup reader (UTF-8 HTML, '
                  '<title> dropped, <pre> layout kept); one page; 64 MiB stored bound'),
    'xml_text': ('body_text xml_text 2026-11-08: spicy-docs body_text xml markup reader (element boundaries '
                 'as line breaks, whitespace-only lines dropped); one page; 64 MiB stored bound'),
    'warc': ('body_text warc 2026-11-08: spicy-docs read_warc_response (one response record, payload SHA-1 '
             'checked), HTTP gzip/deflate content encoding decoded within 64 MiB, payload sniffed and read by '
             'the pdf_text, html_text or xml_text rule above'),
}

# Preserve the existing bundle ID for the exact migration leaf IDs and policy.
MIGRATION_BUNDLE_INPUTS = 'eb1390f56e0216d7ed9ea94db85264a51a2dfd63c1831bc87e2f25c25683bf04'
