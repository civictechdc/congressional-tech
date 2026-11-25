"""Declared meanings of reading rows and combined unreadable decisions."""
READING_VERSIONS = {
    'sniff': '01bf09000fce8229a468583c23f869fc639c56e3e87a1ca447dd66c5f99bff6b',
    'html': '61d7904883f042f48d3732d0518adaa5cf5084790ebc9d5411aad7a6ab605969',
    'xml': 'c9d955b28b401a3fe56386a4a221b3f2147baa0f1da503c7c6a224f4808d085f',
    'json': 'f8d98b4305d8b85bdb6323b91ca56c9c01e0ffd3234ed89d9d90afadc37cae93',
    'house_floor_feed': 'b08fb4d8577bb72a97a0b6624eac8d1d21cee01a2db42184e8f7d38c80423a8f',
    'html_metadata': 'c226ccd99877c497474ffee673baa301f37bc14972b9b9f391af594da9b2b7be',
    'gpo_mods': 'ac383d286e4213e9c8d3e4b90f4c056120db2448309f341c728b7689f0745c07',
    'wikidata_reconcile': '817a4f79b7e35cabf59a96d291d5e53683c0dd3baf58f47e60dd78f5c8293e03',
    'readings': '7b006df14ea065d7bab8c15a319c9201c57d4547c174d722651a33107dbd73ed',
    # Body-text parsers (data model §6.6), declared 2026-11-08: each ID is the SHA-256 of its
    # declaration below, computed once and never recomputed; warc's names the IDs it routes to.
    # pdf_text, html_text, xml_text and warc were redeclared 2026-11-18 for spicy-docs derivation 006
    # (ct-yy1r: CRLF/CR-to-LF boundary normalization before cleanup counting, adjacent text-event
    # coalescing, explicit non-breaking space separation normalized to spaces in final cleanup,
    # indented inline punctuation removal, unique Vision band-edge line retention, and invalid_box
    # native geometry refusal). PyMuPDF, spicy-docs and the macOS build are drift evidence in
    # model/reading-version-diagnostics.json, never inputs.
    'pdf_text': '9df9e8fae788e255563aa60ea7fa8d8a51a9931c89c1aaa172f7f3f3eda86a05',
    'html_text': 'cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f',
    'xml_text': '4b30d66e01cf65a5951d7d95e7e5bb092de8ebbceeba592def22523051665b6f',
    'warc': '1bed4bdbc22fc15d5bb3e1f1e520edd16c7d8075ee75b063e80d0567eafc1569',
}

# What each body-text ID declares. A change to what one of these says is a new ID.
BODY_TEXT_DECLARATIONS = {
    'pdf_text': "body_text pdf_text 2026-11-18: spicy-docs body_text pdf derivation 006 (DocumentExtractor, normalize_gpo_pages, pages joined by one newline); printing continuation ends at the first unknown line; prose bullets survive; whole bill/stage footer labels require printing or numbered-layout evidence; inverted or non-finite native line coordinates refuse as NativeGeometryError(invalid_box); page rule spicy-docs NativeOrOcr over each page's native text as normalize_gpo_pages leaves it, the page alone: recognize a page whole when it has no text layer, when its normalized text carries a control character other than tab and line breaks or U+FFFD, or when it has under 50 non-whitespace characters and draws an image; OCR by Apple Vision, accurate, language correction off, in 3 horizontal bands retaining unique band-edge detections when no neighboring strip matches the line, raw RGB at 200 dpi; failed pages make an error with no text; 64 MiB stored bound",
    'html_text': 'body_text html_text 2026-11-18: spicy-docs body_text htm derivation 006; HTML with supported explicit UTF-8, Windows-1252, ISO-8859-1 or ASCII declarations; absent declaration tries strict UTF-8 then Windows-1252; conflicting or unsupported declarations and undecodable bytes refuse; CRLF and lone CR normalize to LF before cleanup counting and adjacent text events coalesce at the reading boundary; original byte identity, encoding choice and cleanup evidence retained; title, script, style, noscript and template content dropped; ordinary ASCII HTML whitespace collapses across text events while explicit non-breaking spaces preserve separation and normalize to spaces in final cleanup, block breaks, navigation labels and buttons separated, partial-word prose anchors kept; pre layout preserved locally and pure pre bodies keep their original layout; hidden pre tags do not affect visible prose; print EOF markers do not consume block breaks; event bound limits nesting; one page; 64 MiB stored bound',
    'xml_text': 'body_text xml_text 2026-11-18: spicy-docs body_text xml derivation 006; CRLF and lone CR normalize to LF before cleanup counting and adjacent text events coalesce at the reading boundary; generic XML keeps element boundaries as line breaks and whitespace-only lines dropped, including metadata; native bill root with Congressional bill DTD public identifier, House amendment-doc with amend v2.8 20020720 public identifier, and GPO USLM namespace qualify legislative normalization: remove bibliographic metadata and qualified amendment meta-house administrative data, collapse formatting whitespace, remove newline and pretty-print indentation before inline punctuation while keeping explicit horizontal and non-breaking space separation normalized to spaces in final cleanup, known inline citations and amendment sponsors; resolve namespaces per element, retain conservative boundaries for foreign and unknown fields; external DTD declarations are inert and exactly empty internal subsets are allowed without entity expansion or resource loading; original identity and cleanup evidence retained; one page; 64 MiB stored bound',
    'warc': 'body_text warc 2026-11-18: spicy-docs read_warc_response (one response record, payload SHA-1 checked), HTTP gzip/deflate content encoding decoded within 64 MiB, payload sniffed and read by pdf_text 9df9e8fae788e255563aa60ea7fa8d8a51a9931c89c1aaa172f7f3f3eda86a05, html_text cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f or xml_text 4b30d66e01cf65a5951d7d95e7e5bb092de8ebbceeba592def22523051665b6f',
}

# Preserve the existing bundle ID for the exact migration leaf IDs and policy.
MIGRATION_BUNDLE_INPUTS = 'eb1390f56e0216d7ed9ea94db85264a51a2dfd63c1831bc87e2f25c25683bf04'

# New derived source meaning, independent of generic XML and document-text readings.
HOUSE_FLOOR_DECLARATION = 'house_floor_feed 2026-11-13: spicy-docs house-floor-feed/002; complete Atom entries with exact original byte spans and hashes, literal publisher metadata and link occurrences; weekly-page HTML base unless explicit xml:base; preserve repeated IDs and weekly URLs; schedule/discovery only, no prose or legislative actions; a separate extra-leading-slash target repair requires the exact absolute URL elsewhere in the same feed, with raw spellings and repair reason retained; malformed input refuses whole; 64 MiB decoded bound'
HTML_METADATA_DECLARATION = 'html_metadata 2026-11-16: extruct json-ld/opengraph/dublincore/microdata/microformat/rdfa with canonical RDFa blank-node coloring, per-format 10s deadline, comment-tolerant HTML5 prefix and bare-UUID route detection, RDFa content:encoded main-content selection preserving multi-line preformatted transcripts while stripping nested CMS navigation/header/footer/share chrome and retroactive live-CMS Congress banners when page dates/years establish an earlier Congress'
GPO_MODS_DECLARATION = 'gpo_mods 2026-11-20: congress_api.parsers.gpo.parse_mods_document over GovInfo MODS XML; root accessId and preferredCitation plus constituent granule accessId and preferredCitation or root preferredCitation with constituent titleInfo partName/partNumber; normalized whitespace; non-MODS or malformed XML refuses whole; 24 MiB page-parse bound'
WIKIDATA_RECONCILE_DECLARATION = 'wikidata_reconcile 2026-11-25: congress_api.parsers.wikidata_reconcile.reading_row over retained W3C Wikidata reconciliation JSON responses; validates non-empty object mapping query keys to result arrays of finite-scored Q[0-9]+ candidates, emits deterministic sorted query:<key> JSON array fields with Q[0-9]+ type IDs; non-UTF-8, non-JSON, non-finite numbers or malformed candidate objects refuse whole; 24 MiB page-parse bound'

# Opt-in reviewed repairs do not replace the ordinary body-text declarations above.
MARKUP_RECOVERY_BASE_VERSIONS = {
    'html_text': 'cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f',
    'xml_text': '4b30d66e01cf65a5951d7d95e7e5bb092de8ebbceeba592def22523051665b6f',
}

MARKUP_RECOVERY_DECLARATIONS = {
    'html_text': 'body_text html_text reviewed recovery 2026-11-18: opt-in html-windows-1252-v1 over exact reviewed original SHA-256; ordinary html_text cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f must refuse; spicy-docs explicit-html-encoding-candidate-v1 strictly decodes complete Windows-1252, transcodes to UTF-8 and replaces actual encoding meta tags with exact edits retained; original and candidate independently retained; same ordinary HTML consumer runs on candidate; candidate and text SHA-256 must match pinned source review; helper refusal is error without text, identity drift leaves work pending; reading/text key is original body and this separate version; no selection; 64 MiB original/candidate and ordinary worker limits; no OCR or network resources',
    'xml_text': 'body_text xml_text reviewed recovery 2026-11-18: opt-in xml-literals-v1 over exact reviewed original SHA-256; ordinary xml_text 4b30d66e01cf65a5951d7d95e7e5bb092de8ebbceeba592def22523051665b6f must refuse; spicy-docs bounded-literal-xml-candidate-v1 permits only bounded flat internal UTF-8 literals in ordinary element text, retains and removes inert DOCTYPE, substitutes exact reference spans; refuses external/parameter/recursive entities, markup values, non-text references and additional DTD declarations; original and candidate independently retained; same ordinary XML consumer runs on candidate, including generic XML when removed DOCTYPE no longer qualifies legislative cleanup; candidate and text SHA-256 must match pinned source review; helper refusal is error without text, identity drift leaves work pending; reading/text key is original body and this separate version; no selection; 64 MiB original/candidate, 16 KiB declarations, eight definitions, 256-byte literals, 64 references and ordinary worker limits; no OCR or network resources',
}

MARKUP_RECOVERY_VERSIONS = {
    'html_text': 'a298c559dc031d8893e488b2c84de7836386d4a877d96e9e47ad70ee87d87a90',
    'xml_text': '7926854fb7e76b15f28f78124c6111fcd27c819611211eaa7825a19016a0463b',
}

# Historical reviewed-recovery IDs remain selectable in explicit manifests, never executable without one.
RETIRED_MARKUP_RECOVERY_VERSIONS = {
    'html_text': (
        'ef4745f48e0432dd21ae960621589e5d1a1404d2e90f0b35c0618b4b10673a42',
        'a5b966945dbdc938f6577f84f6d4b253d437d9693e2ef143efa8b99b385bdca5',
    ),
    'xml_text': (
        'e11e19e1f5ed946e0fda9259e549ca76dd5488ab2070e85f5624e9e4e9849f27',
        '3470b431897887d3a71c3b24e3f9e1fbf3da7ede0e5c7fa32a8a88100f44e2a5',
    ),
}

# Opt-in completed HTML repairs; ordinary HTML/WARC and encoding recovery keep
# their existing versions until a qualified affected set is selectively adopted.
HTML_CONTENT_SELECTION_BASE_VERSION = 'cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f'
HTML_CONTENT_SELECTION_DECLARATION = 'body_text html_text publisher selection 2026-11-18: opt-in congress-gov-embedded-uslm-bill/001 over original bytes; preserve ordinary html_text cbbcee1bd7cb46be713606435ac7f7c88301484d47998b4c6fc273acec4a350f unless one HTTPS Congress.gov bill text canonical and one balanced xml#billTextUslm.generated-html-container identify exactly one complete UTF-8 bill in the GPO USLM namespace; retain exact original byte span and selected SHA-256; render that fragment through spicy-docs uslm derivation 006; preserve all bill sections, signatures and in-wrapper form content; missing, ambiguous, unqualified, unreadable or empty selected content falls back to the complete ordinary HTML rendition with a reason when the marker was present; no generic form deletion, network or OCR; original body identity, one page, 64 MiB input bound; distinct version for reviewed selective adoption, no ordinary reader or WARC activation'
HTML_CONTENT_SELECTION_VERSION = '51b107b3044555406d0237fbf0bd15a46f3320c9874dc6c5d97da0cd262f345e'

# Additional publisher wrappers have an independent opt-in meaning; True still
# requests the original embedded-bill policy, and default HTML remains unchanged.
HTML_LEGISLATIVE_SELECTION_DECLARATION = 'body_text html_text publisher selection 2026-11-18: opt-in congress-gov-legislative-wrappers/002 over exact original UTF-8 bytes; one HTTPS Congress.gov canonical House bill, House resolution, House joint/concurrent resolution or Senate concurrent resolution text URL; one visible explicit complete xml#billTextUslm.generated-html-container containing a complete GPO USLM bill or pLaw, div.generated-html-container, or pre#billTextContainer; HtmlIndexReader qualifies the canonical head and shared HTML events locate explicit outer wrapper ends while tolerating omitted inner paragraph ends; preserve exact source span and digest without DOM serialization; USLM namespace and complete XML checked by the shared XML reader, then spicy-docs uslm or htm derivation 006 renders the complete selected content including forms, signatures, endorsements and preformatted layout; absent, ambiguous, hidden, incomplete, unqualified, unreadable or empty selection falls back to complete ordinary HTML, retaining the original actual key unless a reviewed candidate is explicitly adopted; embedded-PDF rendition and challenge pages have no inline recovery; distinct candidate version, one page, 64 MiB input, no network, OCR, generic form removal, default/WARC activation or change to congress-gov-embedded-uslm-bill/001'
HTML_LEGISLATIVE_SELECTION_VERSION = 'd61921744487a92b3e3ef74257217c2f79836316cc1e758b1444b1fa31db911b'

# Opt-in Congressional CMS chrome & retroactive Congress-banner stripping policy.
HTML_CMS_CONTENT_SELECTION_DECLARATION = 'body_text html_text publisher selection 2026-11-20: opt-in congressional-cms-main-content/002 over original HTML bytes; skip Congress.gov legislative wrappers and response-role error/wait/feed pages; select single RDFa content:encoded (>=200 chars), single main landmark (>=40 nonspace chars), or body subtree with CMS nav/header/footer/sidebar/share/search/cookie/hidden containers pruned while preserving element tails, preformatted hearing transcripts, tables and inline word boundaries; render pruned UTF-8 HTML fragment through spicy-docs htm derivation 006 and strip standalone retroactive live-CMS Congress banner lines when page dates or prose years establish an earlier Congress; fallback to ordinary html_text when no CMS chrome or banner is removed, when under 40 nonspace characters remain, or when the empirical shrinkage guard fires (cleaned output under 500 UTF-8 bytes and under 10% of an ordinary html_text output of at least 2,000 UTF-8 bytes, fitted to 3 observed main_landmark losses); distinct candidate version, one page, 64 MiB input bound, no network or OCR'
HTML_CMS_CONTENT_SELECTION_VERSION = 'b06d356ad5e3030f93ec02462f0c2f9a24172608ed39d1adfc506546d0e4e33d'
RETIRED_HTML_CMS_CONTENT_SELECTION_VERSIONS = (
    'fe2a39f4f194a8888d38b1e07354f169f80fbed1e36156960a998640628044d7',
    'cda208eb7150cd0c2d7f10684f9dee141ffd3ebd6c5036b0ac695a30cdcc4ac3',
)

# Opt-in verified 1:1 capture-receipt sibling composition for WARC/ARC provider envelopes.
WARC_CAPTURE_PAYLOAD_COMPOSITION_DECLARATION = 'body_text warc capture-payload composition 2026-11-16: opt-in verified 1:1 same-receipt-line capture_evidence composition for application/warc+gzip and application/arc+gzip external/provider-responses envelopes (capture_index>=1, complete=true, http_status=200) whose unique capture_index=0 documents sibling payload_sha256 has a qualified completed pdf_text, html_text or xml_text reading and is not a response-role error, wait, wrapper or feed body; preserves exact payload text, UTF-8 page_offsets, ocr_pages, macos_build and text_sha256, recording payload_sha256, payload_parser, payload_parser_version, receipt_key and receipt_line in readings fields; distinct version for explicit selection'
WARC_CAPTURE_PAYLOAD_COMPOSITION_VERSION = 'fb801220a579f726ed152b0565a910421961c18a9ea3048e0801f085b7f0b05a'

# Opt-in selective Tesseract 5.5.4 + bounded-pixel (adaptive <=200 DPI) PDF recovery policy.
PDF_TESSERACT_SELECTIVE_RECOVERY_DECLARATION = 'body_text pdf_text selective Tesseract 5.5.4 bounded 200 dpi recovery 2026-11-19: opt-in OptInPdfReader(dpi=200, adaptive_max_pixels=True, max_pixels=20000000) and spicy-docs Tesseract (libtesseract 5.5.4 LSTM-only, eng tessdata_fast 7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2, PSM 3, OMP_THREAD_LIMIT=1) with maintained NativeOrOcr (min_chars=50, require_images=True, normalize=gpo_page), NativeGeometryError(invalid_box) and non-PDF markup refusal, and normalize_gpo_pages finishing; supports exact-source page overrides preserving unchanged pages byte-for-byte and adaptive integer DPI <=200 keeping oversized 72-DPI scan renders within 20000000 pixels plus explicit lossless CCW page rotation where reviewed; distinct candidate version for source-reviewed selective adoption'
PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION = '48b19ef730f89d86535af12898f83da4bf6ea152f4700fdeed5bf91b8489cbaf'

# Opt-in selective Tesseract 5.5.4 fixed 300 DPI PDF recovery policy (distinct from adaptive bounded 200 DPI).
PDF_TESSERACT_300DPI_RECOVERY_DECLARATION = 'body_text pdf_text selective Tesseract 5.5.4 fixed 300 dpi recovery 2026-11-19: opt-in OptInPdfReader(dpi=300, adaptive_max_pixels=False, max_pixels=20000000) and spicy-docs Tesseract (libtesseract 5.5.4 LSTM-only, eng tessdata_fast 7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2, PSM 3, OMP_THREAD_LIMIT=1) with maintained NativeOrOcr (min_chars=50, require_images=True, normalize=gpo_page), NativeGeometryError(invalid_box) and non-PDF markup refusal, and normalize_gpo_pages finishing; fixed 300 DPI rendering refusing oversized pages exceeding 20000000 pixels; distinct candidate version for source-reviewed selective adoption'
PDF_TESSERACT_300DPI_RECOVERY_VERSION = 'bd11df6e308e98e9f6922b4dc3e5b518e3dc7f92eeaf371040558eb368fc3912'

# Opt-in native word-spacing (TEXT_INHIBIT_SPACES) and symbol-glyph PDF repair policy.
PDF_NATIVE_SPACING_SYMBOL_REPAIR_DECLARATION = 'body_text pdf_text native spacing and symbol repair 2026-11-18: opt-in OptInPdfReader(native_inhibit_spaces=True) delegating to shared spicy-docs DefaultReader(native_inhibit_spaces=True) to suppress PyMuPDF inferred inter-letter spaces while preserving explicit source spaces, NativeGeometryError(invalid_box) refusal for inverted or non-finite native coordinates, shared font_glyphs symbol mapping and normalize_gpo_pages finishing; scan pages refuse without OCR unless explicitly composed; distinct candidate version requiring alphanumeric subsequence preservation and direct source review before selective adoption'
PDF_NATIVE_SPACING_SYMBOL_REPAIR_VERSION = '68400c11b331c36118857e47a961ecdd90e271b482215440e6713e009ee1fd48'
