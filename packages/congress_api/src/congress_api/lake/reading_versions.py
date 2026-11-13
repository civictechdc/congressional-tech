"""Declared meanings of reading rows and combined unreadable decisions."""
READING_VERSIONS = {
    'sniff': '01bf09000fce8229a468583c23f869fc639c56e3e87a1ca447dd66c5f99bff6b',
    'html': '61d7904883f042f48d3732d0518adaa5cf5084790ebc9d5411aad7a6ab605969',
    'xml': 'c9d955b28b401a3fe56386a4a221b3f2147baa0f1da503c7c6a224f4808d085f',
    'json': 'f8d98b4305d8b85bdb6323b91ca56c9c01e0ffd3234ed89d9d90afadc37cae93',
    'house_floor_feed': 'b08fb4d8577bb72a97a0b6624eac8d1d21cee01a2db42184e8f7d38c80423a8f',
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
    'html_text': 'f1cefe442182dc8e4c456359aebdb37e5c50db6b0abb669b303e05763feb94a3',
    'xml_text': '5a0768bcbaaaf7f67e29e2ff989689b62356579780f99e518d137f7b222c798c',
    'warc': 'c5f198e37dabeba3ac686aa23822437e332fcd6a3de14b67a1797b2731bef3dc',
}

# What each body-text ID declares. A change to what one of these says is a new ID.
BODY_TEXT_DECLARATIONS = {
    'pdf_text': "body_text pdf_text 2026-11-13: spicy-docs body_text pdf derivation 004+gpo.20261113 (DocumentExtractor, normalize_gpo_pages, pages joined by one newline); printing continuation ends at the first unknown line; prose bullets survive; whole bill/stage footer labels require printing or numbered-layout evidence; page rule spicy-docs NativeOrOcr over each page's native text as normalize_gpo_pages leaves it, the page alone: recognize a page whole when it has no text layer, when its normalized text carries a control character other than tab and line breaks or U+FFFD, or when it has under 50 non-whitespace characters and draws an image; OCR by Apple Vision, accurate, language correction off, in 3 horizontal bands, raw RGB at 200 dpi; failed pages make an error with no text; 64 MiB stored bound",
    'html_text': 'body_text html_text 2026-11-13: spicy-docs body_text htm derivation 007+ctreaders.20261113; HTML with supported explicit UTF-8, Windows-1252, ISO-8859-1 or ASCII declarations; absent declaration tries strict UTF-8 then Windows-1252; conflicting or unsupported declarations and undecodable bytes refuse; original byte identity, encoding choice and cleanup evidence retained; title, script, style, noscript and template content dropped; ordinary HTML whitespace collapses across text events with block breaks, navigation labels and buttons separated, partial-word prose anchors kept; pre layout preserved locally and pure pre bodies keep their original layout; hidden pre tags do not affect visible prose; print EOF markers do not consume block breaks; event bound limits nesting; one page; 64 MiB stored bound',
    'xml_text': 'body_text xml_text 2026-11-13: spicy-docs body_text xml derivation 007+ctreaders.20261113; generic XML keeps element boundaries as line breaks and whitespace-only lines dropped, including metadata; native bill root with Congressional bill DTD public identifier, House amendment-doc with amend v2.8 20020720 public identifier, and GPO USLM namespace qualify legislative normalization: remove bibliographic metadata and qualified amendment meta-house administrative data, collapse formatting whitespace, remove pretty-print indentation before sentence punctuation and preserve known inline citations and amendment sponsors; resolve namespaces per element, retain conservative boundaries for foreign and unknown fields; external DTD declarations are inert and exactly empty internal subsets are allowed without entity expansion or resource loading; original identity and cleanup evidence retained; one page; 64 MiB stored bound',
    'warc': 'body_text warc 2026-11-13: spicy-docs read_warc_response (one response record, payload SHA-1 checked), HTTP gzip/deflate content encoding decoded within 64 MiB, payload sniffed and read by pdf_text 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8, html_text f1cefe442182dc8e4c456359aebdb37e5c50db6b0abb669b303e05763feb94a3 or xml_text 5a0768bcbaaaf7f67e29e2ff989689b62356579780f99e518d137f7b222c798c',
}

# Preserve the existing bundle ID for the exact migration leaf IDs and policy.
MIGRATION_BUNDLE_INPUTS = 'eb1390f56e0216d7ed9ea94db85264a51a2dfd63c1831bc87e2f25c25683bf04'

# New derived source meaning, independent of generic XML and document-text readings.
HOUSE_FLOOR_DECLARATION = 'house_floor_feed 2026-11-13: spicy-docs house-floor-feed/002; complete Atom entries with exact original byte spans and hashes, literal publisher metadata and link occurrences; weekly-page HTML base unless explicit xml:base; preserve repeated IDs and weekly URLs; schedule/discovery only, no prose or legislative actions; a separate extra-leading-slash target repair requires the exact absolute URL elsewhere in the same feed, with raw spellings and repair reason retained; malformed input refuses whole; 64 MiB decoded bound'
