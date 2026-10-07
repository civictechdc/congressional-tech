"""Retained event pages and bounded response traces establish these regressions."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.acquisition.documents import resolve_document
from congress_api.acquisition.raw_sync import run_sync
from congress_api.models.content import content_bytes
from congress_api.parsers.archive_links import inspect_capture, related_links
from congress_api.parsers.committee_pages import parse_event_page, document_groups
from congress_api.parsers.document_links import document_links
from congress_api.parsers.senate import parse_page
from congress_api.parsers.senate_page import document_labels
from congress_api.retention.raw_archive import Archive
from test_document_link_probe import response as probe_response
from test_raw_source_sync import MemoryStore, response

FIXTURES = Path(__file__).parent / 'fixtures/meeting_inventory/house-sites/download-wrappers'
SOURCES = json.loads((FIXTURES / 'sources.json').read_text())
BAD = 'https://democrats-transportation.house.gov/download/jared-cassity-testimony&download=1'
GOOD = BAD.replace('&download=1', '?download=1')
PDF = 'https://democrats-transportation.house.gov/imo/media/doc/Jared%20Cassity%20Testimony.pdf'


@pytest.mark.parametrize('source', SOURCES, ids=lambda row: row['site'])
def test_retained_house_events_keep_download_routes_and_originals(source):
    body = (FIXTURES / source['event_file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['event_sha256']
    page = parse_event_page(body, source['page'])
    expected = set(source['missing_urls'])
    assert expected <= {row[2] for row in page['documents']}
    assert expected <= {g['files'][0]['url'] for g in document_groups(body, source['page'], '/event')}
    assert expected <= {link['url'] for link in related_links(body, source['page'], 'html')}
    for url in expected:
        assert page['document_metadata'][url]['occurrences']
    assert content_bytes(page['raw_html']) == body


@pytest.mark.parametrize('source', SOURCES, ids=lambda row: row['site'])
def test_retained_wrappers_keep_the_literal_target_even_when_malformed(source):
    body = (FIXTURES / source['wrapper_file']).read_bytes()
    assert hashlib.sha256(body).hexdigest() == source['wrapper_sha256']
    link, = document_links(body, source['wrapper'])
    assert link.url == source['literal_target']
    assert link.text == 'please click here'
    assert link.attributes['href'].endswith(source['literal_target'].split('/download/')[1])


@pytest.mark.parametrize('origin', ['https://democrats-armedservices.house.gov', 'https://www.epw.senate.gov'])
def test_files_serve_and_download_routes_share_labels_and_witness_context(origin):
    body = b'''<html><h1>Hearing</h1><h2>Witnesses</h2>
      <p>Jane Smith, Scientist, Institute</p><p><a href="/?a=Files.Serve&amp;File_id=abc">Testimony</a></p>
      <p>John Jones, Engineer, Institute</p><p><a href="/download/jones">Testimony</a></p>
      <a href="/wp-content/uploads/logo.png">Logo</a></html>'''
    page = parse_event_page(body, origin+'/hearings/example')
    urls = {origin+'/?a=Files.Serve&File_id=abc', origin+'/download/jones'}
    assert {d[2] for d in page['documents']} == urls
    assert {l.url for l in document_links(body, origin+'/hearings/example')} == urls
    assert page['document_metadata'][origin+'/download/jones']['witness_indexes'] == [1]
    senate = parse_page(body, origin+'/hearings/example')
    assert {d[2] for d in senate.documents} == urls


def test_download_routes_are_not_inferred_from_unrelated_hosts_queries_or_assets():
    body = b'''<html><a href="/download/profile">Profile</a>
      <a href="/redirect?to=/download/profile">Organization</a>
      <a href="/download/logo.png">Logo</a><a href="/events/one">Hearing</a></html>'''
    for url in ['https://example.com/', 'https://senate.gov.example.com/', 'https://house.gov.example.com/']:
        assert document_links(body, url) == []
    assert [l.url for l in document_links(body, 'https://budget.house.gov/')] == ['https://budget.house.gov/download/profile']


def test_legacy_files_serve_path_stays_supported_alongside_query_action():
    body = b'<a href="/public/files.serve?id=abc">Testimony</a>'
    url = 'https://www.epw.senate.gov/hearings/example'
    expected = 'https://www.epw.senate.gov/public/files.serve?id=abc'
    assert [l.url for l in document_links(body, url)] == [expected]
    assert [d[2] for d in parse_page(body, url).documents] == [expected]


def test_senate_label_reader_does_not_promote_relative_navigation_on_a_wrapper():
    body = '<a href="#content">Skip</a><a href="press-release/notice">News</a><a href="/download/file?download=1">Download</a>'
    assert document_labels(body, 'https://www.finance.senate.gov/download/file') == {
        'https://www.finance.senate.gov/download/file?download=1': 'Download'}


def test_probe_fallback_keeps_failed_literal_response_and_uses_normal_step_budget():
    source = next(r for r in SOURCES if r['site']=='transportation.house.gov')
    wrapper = source['wrapper']
    saved = {wrapper: probe_response(wrapper, (FIXTURES/source['wrapper_file']).read_bytes()),
        BAD: probe_response(BAD, b'<html>Gone</html>', status=410),
        GOOD: probe_response(GOOD, status=302, Location=PDF),
        PDF: probe_response(PDF, b'%PDF-1.7\n', media='application/pdf', complete=False)}
    before = deepcopy(saved)
    def no_network(*args, **kwargs):
        pytest.fail('The retained chain is complete')
    result = resolve_document(wrapper, saved=saved, get=no_network, max_steps=4)
    assert result['outcome'] == 'document_identified'
    assert result['resolved_url'] == PDF
    assert [r.url for r in result['responses']] == [wrapper, BAD, GOOD, PDF]
    assert result['responses'][1].status_code == 410
    fallback, = [l for l in result['links'] if l.basis == 'publisher_download_query_fallback']
    assert fallback.url == GOOD and fallback.original_url == BAD
    assert saved == before
    limited = resolve_document(wrapper, saved=saved, get=no_network, max_steps=2)
    assert limited['outcome'] == 'step_limit' and len(limited['responses']) == 2


@pytest.mark.parametrize('url,status', [
    (BAD, 200), (BAD, 403), (BAD, 429), (BAD, 503),
    (BAD.replace('democrats-transportation.house.gov', 'www.finance.senate.gov'), 410),
    (BAD.replace('.house.gov', '.house.gov.example.com'), 410),
    (BAD.replace('/download/', '/other/'), 410),
    (BAD+'?other=1', 410), (BAD.replace('&download=1', '&download=1&other=2'), 410),
    (BAD.replace('.gov/', '.gov:8443/'), 410),
])
def test_fallback_never_rewrites_unproven_routes_or_retryable_responses(url, status):
    outcome, links = inspect_capture(response(url, b'<html>Unavailable</html>', 'text/html', status=status))
    assert links == []
    assert outcome == ('html' if status == 200 else 'http_error')


def test_successful_literal_ampersand_route_still_wins():
    result = resolve_document(BAD, saved={BAD: probe_response(BAD, b'%PDF-1.7', media='application/pdf')})
    assert result['resolved_url'] == BAD and result['links'] == []
    assert inspect_capture(response(BAD, b'%PDF-1.7'))[1] == []


@pytest.mark.parametrize('status', [404, 410])
def test_capture_fallback_uses_queue_and_keeps_failure_receipt(status):
    from io import BytesIO
    from pypdf import PdfWriter

    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    stream = BytesIO()
    pdf.write(stream)
    store = MemoryStore()
    def fetch(url):
        assert url in {BAD, GOOD}
        return response(url, b'<html>Gone</html>', 'text/html', status=status) if url==BAD else response(url, stream.getvalue())
    # A fallback is a queued candidate, not an uncounted request inside a task.
    stats = run_sync(Archive(store, 'bad-route'), [{'url':BAD}], fetch=fetch, limit=1, workers=1)
    assert stats['attempted'] == 1
    state = Archive(store,'inspect').state
    assert state[BAD]['outcome'] == 'http_error' and state[BAD]['http_status'] == status
    assert state[GOOD]['outcome'] == 'pending'
    receipts = [json.loads(line) for key, value in store.objects.items() if key.startswith('receipts/') for line in gzip.decompress(value).splitlines()]
    failed, = [r['record'] for r in receipts if r['record']['requested_url']==BAD]
    assert failed['links'][0]['original_url'] == BAD
    assert failed['links'][0]['basis'] == 'publisher_download_query_fallback'
    resumed = run_sync(Archive(store,'good-route'), [], fetch=fetch, limit=1, workers=1, initial_only=True)
    assert resumed['attempted'] == 1 and resumed['saved'] == 1
    assert Archive(store,'final').state[BAD]['http_status'] == status


def test_incomplete_failed_response_does_not_generate_a_fallback():
    value = response(BAD,b'<html>partial','text/html',status=410)
    value['complete'] = False
    assert inspect_capture(value)[1] == []


def test_native_capture_keeps_the_actionable_direct_failure_without_a_provider_request(tmp_path, monkeypatch):
    from congress_api.transport.rust_fetch import RustFetcher
    from test_rust_fetch_retry import native_worker

    monkeypatch.setenv('ZYTE_TOKEN', 'fixture-token')
    binary, calls = native_worker(tmp_path, status=410, retry_after=None, body=b'<html>Gone</html>')
    with RustFetcher(binary) as fetcher:
        result, inspection = fetcher.fetch_spooled(BAD, before_read=lambda: None)
    assert result['http_status'] == 410
    assert inspection[0] == 'http_error' and inspection[1][0]['url'] == GOOD
    assert [json.loads(line)['transport'] for line in calls.read_text().splitlines()] == ['direct']
