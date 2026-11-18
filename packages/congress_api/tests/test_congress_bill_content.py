"""Source-backed Congress.gov selection with explicit ordinary-reader fallbacks."""
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from congress_api.lake.reading_versions import (
    HTML_CONTENT_SELECTION_BASE_VERSION,
    HTML_CONTENT_SELECTION_DECLARATION,
    HTML_CONTENT_SELECTION_VERSION,
    READING_VERSIONS,
)
from congress_api.parsers.body_text import markup_text
from congress_api.parsers.congress_bill_content import select_congress_bill_content

FIXTURES = Path(__file__).parent / 'fixtures'
BILL = FIXTURES / 'congress_bill_content'
CANONICAL = b'https://www.congress.gov/bill/119th-congress/house-bill/4307/text'
NAMESPACE = b'http://schemas.gpo.gov/xml/uslm'


def page(content=b'<section><p>Strike section 2.</p></section>'):
    return (b'<html><head><link rel="canonical" href="' + CANONICAL + b'"></head><body>'
            b'<form><select><option>Unrelated member</option></select></form>'
            b'<xml id="billTextUslm" class="generated-html-container">'
            b'<bill xmlns="' + NAMESPACE + b'">' + content + b'</bill></xml></body></html>')


def selected(body):
    return markup_text(body, 'html_text', select_publisher_content=True)


def test_source_backed_bill_preserves_all_sections_and_both_signatures():
    body = gzip.decompress((BILL / 'hr4307-enrolled.html.gz').read_bytes())
    assert sha256(body).hexdigest() == 'a6fb358f8a7c567829dafb5493ec352b88cd22a0ce835ec8bbf01237a9b47471'
    expected = (BILL / 'hr4307-enrolled.txt').read_text()
    # This complete expected text was directly reviewed against the source bill,
    # including every nested clause and both signature blocks; it is not a count.
    reading = selected(body)
    assert reading.status == 'completed' and reading.text == expected
    assert len(reading.text.encode()) == 4370
    assert reading.page_offsets == (0,) and reading.ocr_pages == ()
    assert reading.fields['page_count'] == 1
    assert reading.fields['source_sha256'] == sha256(body).hexdigest()
    selection = select_congress_bill_content(body)
    evidence = json.loads(reading.fields['content_selection'])
    assert evidence['outcome'] == 'selected' and evidence['output_rendition'] == 'uslm'
    assert (evidence['byte_start'], evidence['byte_end']) == (355991, 366629)
    assert selection.body == body[evidence['byte_start']:evidence['byte_end']]
    assert sha256(selection.body).hexdigest() == evidence['selected_sha256']
    assert sha256(reading.text.encode()).hexdigest() == 'c513d914c7ebb4f95e17ed58eee29b2db04fca6ec2e42b8b4d38dcbe2508bfad'
    # Default html_text reflects its redeclared 2026-11-18 006 derivation (preserving literal &nbsp; spacing).
    baseline = markup_text(body, 'html_text')
    assert sha256(baseline.text.encode()).hexdigest() == '40a718fb7aec68f240f219a21211af4243fc5356cfaa5c916c9fc75d45cc710f'
    assert 'content_selection' not in baseline.fields


def test_short_bill_and_legitimate_in_bill_form_keep_their_complete_text():
    assert selected(page()).text == 'Strike section 2.'
    source = page(b'<section><p>Submit this application.</p><form><label>Election</label>'
                  b'<select><option>Individual</option><option>Organization</option></select>'
                  b'</form><p>Signature required.</p></section>')
    assert selected(source).text == 'Submit this application.\nElection\nIndividual\nOrganization\nSignature required.'


@pytest.mark.parametrize('source', [
    b'<html><body><pre>WITNESS\n\n  A    B\n  1    2\n</pre></body></html>',
    b'<html><body><form><label>Apply</label><select><option>Yes</option><option>No</option>'
    b'</select><p>Signature required.</p></form></body></html>',
    b'<html><body><p>Amendment: strike section 2.</p></body></html>',
    (FIXTURES / 'gpo_metadata/CHRG-115hhrg33061.htm').read_bytes(),
])
def test_unmarked_hearing_form_and_short_amendment_are_unchanged(source):
    assert selected(source) == markup_text(source, 'html_text')


@pytest.mark.parametrize(('old', 'new', 'reason'), [
    (b'generated-html-container', b'other-container', 'unqualified_wrapper'),
    (b'<xml id=', b'<xml hidden id=', 'unqualified_wrapper'),
    (CANONICAL, b'https://example.org/bill/119th-congress/house-bill/4307/text', 'unqualified_publisher'),
    (b'<link rel="canonical"', b'<link rel="alternate"', 'missing_or_ambiguous_publisher'),
    (b'</head>', b'<link rel="canonical" href="' + CANONICAL + b'"></head>', 'missing_or_ambiguous_publisher'),
    (b'</xml>', b'</xml><xml id="billTextUslm" class="generated-html-container"></xml>', 'missing_or_ambiguous_wrapper'),
    (b'</xml>', b'<p>Additional substantive passage</p></xml>', 'incomplete_or_ambiguous_bill'),
    (b'</xml>', b'', 'unqualified_markup'),
    (NAMESPACE, b'urn:other', 'incomplete_or_ambiguous_bill'),
    (b'Strike section 2.', b'&unresolved;', 'unreadable_selected_bill'),
    (b'<section><p>Strike section 2.</p></section>', b'', 'empty_selected_bill'),
])
def test_unqualified_candidate_uses_complete_ordinary_text(old, new, reason):
    source = page().replace(old, new)
    baseline = markup_text(source, 'html_text')
    candidate = selected(source)
    assert (candidate.status, candidate.text, candidate.page_offsets) == (
        baseline.status, baseline.text, baseline.page_offsets)
    assert 'Unrelated member' in candidate.text  # fallback keeps the whole body
    evidence = json.loads(candidate.fields['content_selection'])
    assert evidence['outcome'] == 'fallback' and evidence['reason'] == reason


def test_failed_full_fallback_keeps_selection_reason_and_does_not_claim_empty_success():
    source = page().replace(b'Strike section 2.', b'\x81')
    reading = selected(source)
    assert reading.status == 'error' and reading.text is None
    assert reading.fields['source_sha256'] == sha256(source).hexdigest()
    assert json.loads(reading.fields['content_selection'])['outcome'] == 'fallback'


def test_publisher_content_version_is_separate_and_cannot_be_requested_for_xml():
    assert HTML_CONTENT_SELECTION_VERSION == sha256(HTML_CONTENT_SELECTION_DECLARATION.encode()).hexdigest()
    assert HTML_CONTENT_SELECTION_VERSION != HTML_CONTENT_SELECTION_BASE_VERSION
    assert READING_VERSIONS['html_text'] == HTML_CONTENT_SELECTION_BASE_VERSION
    with pytest.raises(ValueError, match='requires html_text'):
        markup_text(b'<bill/>', 'xml_text', select_publisher_content=True)
