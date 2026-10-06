"""Failure audit regressions exercise public parsers and the capture writer."""

from congress_api.parsers.archive_links import inspect_capture, related_links
from congress_api.parsers.senate import parse_page
from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.raw_archive import Archive
from test_raw_source_sync import MemoryStore, response


def test_senate_capture_uses_shared_document_interpretation():
    url = 'https://www.finance.senate.gov/hearings/example'
    body = b'''<html><title>Committee hearing</title><h2>Witness Testimony</h2>
      <a href="/download/06082023-cooper-testimony">Download Testimony</a></html>'''
    target = 'https://www.finance.senate.gov/download/06082023-cooper-testimony'
    parsed = parse_page(body, url).source_dict()
    links = related_links(body, url, 'html')
    link = next(link for link in links if link['url'] == target)
    assert link['context']['document_metadata'] == parsed['document_metadata'][target]
    store = MemoryStore()
    stats = run_sync(Archive(store, 'senate-source'), [{'url': url}],
        fetch=lambda _: response(url, body, 'text/html'), limit=1)
    assert stats['saved'] == 1
    state = Archive(store, 'read').state
    assert state[target]['outcome'] == 'pending'
    assert inspect_capture(response(url, body, 'text/html'))[0] == 'saved'


def test_epw_downloads_and_generic_embeds_are_both_retained():
    url = 'https://www.epw.senate.gov/public/index.cfm/hearings?ID=example'
    body = b'''<html><h2>Witnesses</h2><a href="/public/?a=Files.Serve&amp;File_id=123">Smith Testimony.pdf</a>
      <object type="application/pdf" data="/other.pdf"></object></html>'''
    links = related_links(body, url, 'html')
    assert {link['url'] for link in links} == {
        'https://www.epw.senate.gov/public/?a=Files.Serve&File_id=123',
        'https://www.epw.senate.gov/other.pdf'}


def test_non_senate_navigation_does_not_use_committee_rules():
    assert related_links(b'<html><a href="/download/profile">Download profile</a></html>',
                         'https://senate.gov.example.com/page', 'html') == []


def test_capture_reports_local_size_limit_separately_from_interruption():
    for error in ('response_limit', 'source_response_limit', 'provider_response_limit'):
        capture = response('https://example.gov/a.pdf', b'%PDF partial')
        capture.update(complete=False, error=error)
        assert inspect_capture(capture) == ('size_limit', [])
    for body in (b'', b'%PDF partial'):
        capture = response('https://example.gov/a.pdf', body)
        capture.update(complete=False, error='timeout')
        assert inspect_capture(capture) == ('timeout', [])


def test_size_limited_direct_capture_skips_provider_and_preserves_bytes(tmp_path):
    from congress_api.transport.rust_fetch import RustFetcher, RustResponse
    from congress_api.models.content import content_bytes

    class LimitedFetcher(RustFetcher):
        def __init__(self):
            self.max_bytes = 12
            self.calls = []

        def _request(self, url, transport, **kwargs):
            self.calls.append(transport)
            assert transport == 'direct', 'A provider cannot change our own byte limit'
            path = tmp_path / 'limited.body'
            path.write_bytes(b'%PDF partial')
            return RustResponse(dict(body_file=str(path), http_status=200, final_url=url,
                response_header_items=[], complete=False, error='response_limit'), tmp_path)

    fetcher = LimitedFetcher()
    result, inspection = fetcher._fetch('https://example.gov/a.pdf', transport='auto')
    assert inspection == ('size_limit', [])
    assert result['error'] == 'response_limit'
    assert content_bytes(result['content']) == b'%PDF partial'
    assert fetcher.calls == ['direct']


def test_non_utf8_senate_retains_generic_links_and_enrichment_diagnostic():
    url = 'https://www.finance.senate.gov/hearings/example'
    body = b'<html><meta charset="windows-1252"><a href="/a.pdf">Senator\x92s statement</a></html>'
    capture = response(url, body, 'text/html; charset=windows-1252')
    outcome, links = inspect_capture(capture)
    assert outcome == 'saved'
    assert links[0]['url'] == 'https://www.finance.senate.gov/a.pdf'
    assert capture['link_interpretation_warnings'] == [{'reader': 'senate', 'error_type': 'UnicodeDecodeError'}]
