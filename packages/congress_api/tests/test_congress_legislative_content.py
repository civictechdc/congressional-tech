"""Complete source-reviewed legislative blocks and conservative fallback controls."""
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from congress_api.lake.reading_versions import (
    HTML_CONTENT_SELECTION_VERSION, HTML_LEGISLATIVE_SELECTION_DECLARATION,
    HTML_LEGISLATIVE_SELECTION_VERSION, READING_VERSIONS,
)
from congress_api.parsers.body_text import markup_text
from congress_api.parsers.congress_legislative_content import POLICY

FIXTURES = Path(__file__).parent / 'fixtures/congress_legislative_content'
CANONICAL = b'https://www.congress.gov/bill/118th-congress/house-bill/1240/text'


def page(wrapper):
    return (b'<html><head><link rel="canonical" href="' + CANONICAL + b'"></head><body>'
            b'<form><select><option>Unrelated member</option></select></form>' + wrapper
            + b'<footer>Site Content</footer></body></html>')


def selected(source):
    return markup_text(source, 'html_text', select_publisher_content=POLICY)


@pytest.mark.parametrize(('name', 'source_sha', 'family'), [
    ('pl118-68', '55bdbd8005d416b638bfdb4f5b75246fd42c02d195a7ea9cf808913021e1f87a', 'uslm_pLaw'),
    ('hr1709-engrossed', '1c39723c8130ebe9e053e2a809655fc2a1dab55450e34b2ffbc83d253e94b8a7', 'generated_html'),
    ('hr3916-introduced', 'b33e949a6a98994d7a86815ea7abadb72da2cb5a908d526e948dcbdd0b2235de', 'preformatted'),
    ('hres487-engrossed', 'fb8ab00d5f6d811412dc825269557cae66c7eb752a12e2237e6745a6ae04bd9f', 'generated_html'),
])
def test_complete_source_reviewed_text(name, source_sha, family):
    source = gzip.decompress((FIXTURES / f'{name}.html.gz').read_bytes())
    assert sha256(source).hexdigest() == source_sha
    reading = selected(source)
    # Full expected files were read against every clause, signature, endorsement
    # and preformatted line in these short original legislative bodies.
    assert reading.status == 'completed'
    assert reading.text == (FIXTURES / f'{name}.txt').read_text()
    assert reading.page_offsets == (0,) and reading.ocr_pages == ()
    evidence = json.loads(reading.fields['content_selection'])
    assert evidence['outcome'] == 'selected' and evidence['family'] == family
    assert sha256(source[evidence['byte_start']:evidence['byte_end']]).hexdigest() == evidence['selected_sha256']
    assert reading.fields['source_sha256'] == source_sha
    assert 'Unrelated member' not in reading.text and 'Site Content' not in reading.text


def test_complete_short_html_preserves_legitimate_forms_and_omitted_p_ends():
    source = page(b'<div class="generated-html-container"><p>Strike section 2.'
                  b'<p>Submit this application.<form><label>Election</label>'
                  b'<select><option>Individual</option><option>Organization</option></select>'
                  b'</form><p>Signature required.</div>')
    assert selected(source).text == ('Strike section 2.\nSubmit this application.\nElection\n'
                                     'Individual\nOrganization\nSignature required.')


def test_preformatted_columns_and_blank_lines_survive():
    source = page(b'<pre id="billTextContainer">\n  A    B\n  1    2\n\n  Strike section 2.\n</pre>')
    assert selected(source).text == '\n  A    B\n  1    2\n\n  Strike section 2.\n'


@pytest.mark.parametrize('wrapper', [
    b'<form><label>Apply</label><select><option>Yes</option><option>No</option></select></form>',
    b'<p>Amendment: strike section 2.</p>',
    b'<pre>WITNESS\n\n  A    B\n  1    2\n</pre>',
    b'<embed src="/117/statute/example.pdf" type="application/pdf">',
])
def test_unmarked_documents_keep_the_ordinary_complete_reader(wrapper):
    assert selected(page(wrapper)) == markup_text(page(wrapper), 'html_text')


@pytest.mark.parametrize('source', [
    page(b'<div class="generated-html-container"><p>Text</p>'),
    page(b'<div class="generated-html-container"><p>Text</p></div>').replace(b'</html>', b''),
    page(b'<div hidden class="generated-html-container"><p>Text</p></div>'),
    page(b'<section hidden><div class="generated-html-container"><p>Text</p></div></section>'),
    page(b'<template><div class="generated-html-container"><p>Text</p></div></template>'),
    page(b'<div class="generated-html-container"><p>Text</p></div>' * 2),
    page(b'<div class="generated-html-container" class="other"><p>Text</p></div>'),
    page(b'<div class="generated-html-container"></div>'),
    page(b'<xml id="billTextUslm" class="generated-html-container"><pLaw xmlns="urn:other"><p>Text</p></pLaw></xml>'),
    page(b'<xml id="billTextUslm" class="generated-html-container"><pLaw xmlns="http://schemas.gpo.gov/xml/uslm"><p>Text</p></pLaw><p>Additional clause</p></xml>'),
    page(b'<div class="generated-html-container"><p>Text</p></div>').replace(CANONICAL, b'https://example.org/bill/118th-congress/house-bill/1240/text'),
    page(b'<div class="generated-html-container"><p>Text</p></div>').replace(b'rel="canonical"', b'rel="alternate"'),
    page(b'<div class="generated-html-container"><p>Text</p></div>').replace(b'</head>', b'<link rel="canonical" href="' + CANONICAL + b'"></head>'),
    page(b'<div class="generated-html-container"><p>Text</p></div>').replace(b'/house-bill/', b'/committee/'),
])
def test_unqualified_candidates_fall_back_without_silent_text_loss(source):
    prior, candidate = markup_text(source, 'html_text'), selected(source)
    assert (candidate.status, candidate.text, candidate.page_offsets) == (prior.status, prior.text, prior.page_offsets)
    assert json.loads(candidate.fields['content_selection'])['outcome'] == 'fallback'


def test_source_reading_failure_remains_error_and_keeps_evidence():
    source = page(b'<div class="generated-html-container">\x81</div>')
    reading = selected(source)
    assert reading.status == 'error' and reading.text is None
    assert reading.fields['source_sha256'] == sha256(source).hexdigest()
    assert json.loads(reading.fields['content_selection'])['outcome'] == 'fallback'


def test_policy_has_an_explicit_distinct_version_and_does_not_change_true():
    assert HTML_LEGISLATIVE_SELECTION_VERSION == sha256(HTML_LEGISLATIVE_SELECTION_DECLARATION.encode()).hexdigest()
    assert HTML_LEGISLATIVE_SELECTION_VERSION not in {HTML_CONTENT_SELECTION_VERSION, READING_VERSIONS['html_text']}
    source = page(b'<div class="generated-html-container">Strike section 2.</div>')
    assert markup_text(source, 'html_text', select_publisher_content=True) == markup_text(source, 'html_text')
    with pytest.raises(ValueError, match='Unknown publisher'):
        markup_text(source, 'html_text', select_publisher_content='unknown-policy')
    with pytest.raises(ValueError, match='requires html_text'):
        markup_text(b'<bill/>', 'xml_text', select_publisher_content=POLICY)
