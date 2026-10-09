"""Exact retained publisher evidence for the independently reviewed parser gaps."""
import gzip
import hashlib
import html
import json
from functools import lru_cache
from pathlib import Path

import pytest

from congress_api.models.content import content_bytes
from congress_api.parsers.committee_pages import parse_event_page
from congress_api.parsers.document_links import http_url

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/shape-audit'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text())['cases']
CASES = [(source, finding) for source in SOURCES for finding in source['critical']]
NON_DOCUMENT = {'webcast', 'registration', 'registration_intake', 'repository', 'committee repository'}
KINDS = {'questions_for_record': 'questions for the record', 'record_submission': 'support document',
         'bill_text': 'legislative text', 'hearing_notice': 'hearing notice', 'meeting notice': 'hearing notice',
         'report': 'committee report'}


@lru_cache
def parsed(source_id):
    source = next(s for s in SOURCES if s['id'] == source_id)
    body = gzip.decompress((FIXTURES / source['file']).read_bytes())
    assert hashlib.sha256(body).hexdigest() == source['sha256']
    page = parse_event_page(body, source['url'])
    assert content_bytes(page['raw_html']) == body
    return page


@pytest.mark.parametrize('source,finding', CASES, ids=[f['id'] for _, f in CASES])
def test_confirmed_retained_source_gaps(source, finding):
    page = parsed(source['id'])
    docs = {d[2]: d for d in page['documents']}
    target = finding['target']
    if finding['disposition'] == 'confirmed_local_omission':
        assert target in docs
        occurrences = page['document_metadata'][target]['occurrences']
        # The audit quotes HTML source attributes; the DOM decodes entities once.
        assert any(a.get('href') in [html.unescape(href) for href in finding['attributes']]
                   for o in occurrences for a in o['attributes'])
    elif finding['scope'] == 'related_page_metadata' or finding['role'] in NON_DOCUMENT:
        assert target not in docs
        links = [link for link in page['page_metadata']['links']
                 if http_url(link['attributes'].get('href', ''), source['url']) == target]
        assert links
        assert any(link.get('related_page', {}).get('role') in
                   {'media', 'repository', 'registration', 'related_coverage'} for link in links)
        assert all(link.get('related_page', {}).get('role') != 'witness_reference' for link in links)
    else:
        expected = KINDS.get(finding['role'], 'witness statement')
        assert docs[target][0] == expected
        assert docs[target][0] not in finding['baseline_kinds']


@pytest.mark.parametrize('body', [
    '<h2>Witnesses</h2><p>Jane Doe</p><p><a href="/node/7">Her organization</a></p>',
    '<h2>Materials</h2><p><a href="https://thomas.loc.gov/cgi-bin/query/z?c111:HR1:">H.R.1</a></p>',
    '<p><a href="/documents">Witness List and Testimony</a> (Not Yet Available)</p>',
    '<nav><a href="/committee-report/a">Report</a></nav>',
    '<p><a href="#missing">Transcript</a></p>',
    '<h2>Submissions for the Record</h2><a href="/submit">Submit testimony</a>',
])
def test_ambiguous_and_non_material_references_stay_out(body):
    assert not parse_event_page(body.encode(), 'https://example.house.gov/hearings/a')['documents']


def test_explicit_pdf_overrides_a_misleading_repository_label():
    page = parsed('r021')
    assert any(d[1] == 'Committee Repository' and '.pdf' in d[2] for d in page['documents'])


@pytest.mark.parametrize('href,label', [
    ('https://congress.gov/bill/111th-congress/house-bill/7', 'H.R. 7'),
    ('https://example.house.gov/publications/report', 'Budget publications'),
    ('https://example.house.gov/publications/report/', 'Budget publications'),
    ('https://example.net/committee-report/a', 'Related organization'),
    ('https://example.net/publications/research', 'Our organization'),
    ('https://example.net/publications', 'Published research'),
    ('https://example.house.gov/opening-statements', 'Statements'),
    ('https://congress.gov/bill/111th-congress/house-bill/7?view=/text', 'H.R. 7'),
])
def test_publication_indexes_and_general_records_are_not_documents(href, label):
    body = f'<section><a href="{href}">{label}</a></section>'.encode()
    page = parse_event_page(body, 'https://example.house.gov/hearings/a')
    assert not page['documents']
    assert page['page_metadata']['links'][0]['attributes']['href'] == href


@pytest.mark.parametrize('label,kind', [
    ('Witness Statement', 'witness statement'),
    ('Text of H.R. 47', 'legislative text'),
    ('Meeting notice', 'hearing notice'),
    ('Statement Submitted for the Record', 'support document'),
    ('Responses to questions submitted for the record after the transcript', 'questions for the record'),
    ('Monetary Policy Report', 'committee report'),
])
def test_specific_document_label_overrides_broad_statement_heading(label, kind):
    page = parse_event_page(f'<h2>Opening Statements</h2><a href="/file.pdf">{label}</a>'.encode(),
                            'https://example.house.gov/hearings/a')
    assert page['documents'][0][0] == kind


def test_media_and_registration_prose_does_not_override_a_document_label():
    body = b'''<p>To register for the hearing, consult the <a href="/statement/1">opening statement</a>.</p>
    <p>This hearing will be live-streamed. <a href="/statement/2">Opening Statement</a></p>
    <p><a href="/statement/3">Prepared statement</a> and <a href="/pending">Witness list</a> (Not Yet Available)</p>'''
    page = parse_event_page(body, 'https://example.house.gov/hearings/a')
    assert {d[2] for d in page['documents']} == {f'https://example.house.gov/statement/{n}' for n in (1, 2, 3)}


def test_joint_document_occurrences_keep_separate_literal_owner_labels():
    page = parsed('r054')
    target = next(f['target'] for s in SOURCES if s['id'] == 'r054' for f in s['critical'])
    occurrences = page['document_metadata'][target]['occurrences']
    assert len(occurrences) == 3
    assert len({tuple(o['labels']) for o in occurrences}) == 3


def test_document_row_does_not_describe_another_row_or_a_merged_cell():
    body = b'''<table><thead><tr><th>Name</th><th>Document</th></tr></thead><tbody>
      <tr><td>Testimony from the agency</td><td><a href="/one">Document</a></td></tr>
      <tr><td>An organization</td><td><a href="/two">Document</a></td></tr>
      <tr><td colspan="2">Testimony from an agency <a href="/three">Document</a></td></tr>
    </tbody></table>'''
    page = parse_event_page(body, 'https://example.house.gov/hearings/a')
    assert page['documents'] == [['witness statement', 'Document', 'https://example.house.gov/one']]


def test_retained_unavailable_composite_is_not_the_preceding_advisory():
    assert not any('formmode=wlprint' in d[2] for d in parsed('d012')['documents'])


def test_member_label_does_not_inherit_a_witness_role():
    statements = [d for d in parsed('c043')['documents'] if 'Opening Statement' in d[1]]
    assert statements and all(d[0] == 'member statement' for d in statements)


def test_witness_document_field_keeps_biographies_separate():
    body = b'''<div class="witnesses-testimonies"><span class="witness-document">
        <a href="/files/Jane-Bio.pdf">Document</a></span></div>'''
    page = parse_event_page(body, 'https://example.house.gov/hearings/a')
    assert page['documents'][0][0] == 'witness biography'
