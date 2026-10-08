import httpx
import pytest

from congress_api.acquisition.documents import resolve_document
from congress_api.models.content import RawContent
from congress_api.models.documents import DocumentProbeResponse
from congress_api.parsers.document_links import document_links
from congress_api.transport.document_probe import get_prefix


def response(url, body=b'', status=200, media='text/html', complete=True, **headers):
    return DocumentProbeResponse(url=url, status_code=status, headers=headers,
        header_items=list(headers.items()), content=RawContent.from_bytes(body, media), complete=complete)


def test_saved_cardin_landing_page_and_pdf_need_no_network():
    url = 'https://www.finance.senate.gov/download/-7202023-cardin-statement'
    pdf = url + '&download=1'
    saved = {url: response(url, f'<a href="{pdf.replace("&", "&amp;")}">please click here</a>'.encode()),
             pdf: response(pdf, b'%PDF-1.7\n', media='application/pdf', complete=False)}
    def no_network(*a, **k):
        pytest.fail('Saved responses should be reused.')
    result = resolve_document(url, saved=saved, get=no_network)
    assert result['outcome'] == 'document_identified' and result['format'] == 'pdf'
    assert result['resolved_url'] == pdf
    assert result['links'][0].attributes['href'] == pdf
    assert not result['responses'][-1].complete


def test_html_download_base_embeds_and_meta_refresh_preserve_evidence():
    links = document_links(b'''<base href="/files/"><a href="person.pdf">Testimony of Example</a>
        <a href="/navigation">Home</a><a download href="report?id=42">Report</a>
        <iframe src="book.pdf"></iframe><meta http-equiv="refresh" content="0; URL='../next'">
        <a download href="javascript:alert(1)">No</a>''', 'https://x.test/page')
    assert [link.url for link in links] == ['https://x.test/files/person.pdf',
        'https://x.test/files/report?id=42', 'https://x.test/files/book.pdf', 'https://x.test/next']
    assert links[0].text == 'Testimony of Example'
    assert links[-1].basis == 'meta_refresh'


@pytest.mark.parametrize(('complete', 'outcome'), [(True, 'no_download_link'), (False, 'html_limit')])
def test_truncated_html_is_not_reported_as_no_download(complete, outcome):
    url = 'https://x.test/'
    result = resolve_document(url, saved={url: response(url, b'<html>No link</html>', complete=complete)})
    assert result['outcome'] == outcome


def test_multiple_downloads_are_candidates_not_an_arbitrary_winner():
    url = 'https://x.test/'
    result = resolve_document(url, saved={url: response(url, b'<a href="1.pdf">One</a><a href="2.pdf">Two</a>')})
    assert result['outcome'] == 'multiple_downloads'
    assert len(result['links']) == 2
    assert result['resolved_url'] is None


def test_http_errors_and_claimed_pdf_html_are_not_verified_documents():
    url = 'https://x.test/report.pdf'
    for status, outcome in [(404, 'http_error'), (200, 'no_download_link')]:
        result = resolve_document(url, saved={url: response(url, b'<html>Unavailable</html>',
                                                          status=status, media='application/pdf')})
        assert result['outcome'] == outcome
    result = resolve_document(url, saved={url: response(url, b'not pdf', media='application/pdf')})
    assert result['outcome'] == 'unverified_content'


def test_redirect_loop_and_total_step_limit():
    url = 'https://x.test/a'
    urls = []
    def get(target, **kwargs):
        urls.append(target)
        return response(target, status=302, Location=target + 'a')
    result = resolve_document(url, get=get, max_steps=3)
    assert result['outcome'] == 'step_limit'
    assert len(urls) == 3
    result = resolve_document(url, saved={url: response(url, status=302, Location='/a')})
    assert result['outcome'] == 'loop'
    result = resolve_document(url, saved={url: response(url, b'<a href="/a">Download</a>')})
    assert result['outcome'] == 'no_download_link'
    assert result['links'] == []
    assert len(result['responses']) == 1
    result = resolve_document(url, saved={
        url: response(url, b'<a href="/b">Download</a>'),
        'https://x.test/b': response('https://x.test/b', b'<a href="/a">Download</a>')})
    assert result['outcome'] == 'loop'
    assert len(result['responses']) == 2


@pytest.mark.parametrize(('body', 'kind'), [(b'PK\x03\x04data', 'zip'), (b'{\\rtf1 data}', 'rtf'),
    (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1data', 'legacy_office'), (b'<?xml version="1.0"?><doc/>', 'xml')])
def test_other_document_signatures_are_identified_without_full_validation(body, kind):
    url = 'https://x.test/file'
    result = resolve_document(url, saved={url: response(url, body, media='application/octet-stream')})
    assert result['outcome'] == 'document_identified'
    assert result['format'] == kind


class CountingStream(httpx.SyncByteStream):
    def __init__(self, prefix=b'x', chunks=10000):
        self.prefix, self.chunks, self.reads, self.closed = prefix, chunks, 0, False

    def __iter__(self):
        for i in range(self.chunks):
            self.reads += 1
            yield (self.prefix if i == 0 else b'').ljust(1024, b'x')

    def close(self):
        self.closed = True


def test_stream_byte_limit_even_when_server_ignores_range(monkeypatch):
    monkeypatch.setattr('congress_api.transport.document_probe.pace_request', lambda url: None)
    stream = CountingStream(b'<html>')
    def handle(request):
        assert request.method == 'GET'
        assert request.headers['range'] == 'bytes=0-2047'
        assert request.headers['accept-encoding'] == 'identity'
        return httpx.Response(200, stream=stream, headers={'Content-Type': 'text/html'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = get_prefix('https://x.test/', client=client, max_bytes=2048)
    assert len(result.content.body_bytes()) == 2048
    assert stream.reads == 2 and stream.closed
    assert not result.complete


def test_redirect_body_is_never_consumed_and_pdf_stops_after_magic(monkeypatch):
    monkeypatch.setattr('congress_api.transport.document_probe.pace_request', lambda url: None)
    redirect, pdf = CountingStream(), CountingStream(b'%PDF-1.7\n')
    def handle(request):
        if request.url.path == '/':
            return httpx.Response(302, headers={'Location': '/file'}, stream=redirect)
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'}, stream=pdf)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = resolve_document('https://x.test/', get=lambda url, **kw: get_prefix(url, client=client, **kw))
    assert result['outcome'] == 'document_identified'
    assert redirect.reads == 0 and redirect.closed
    assert pdf.reads == 1 and pdf.closed
    assert len(result['responses']) == 2


def test_compressed_response_is_not_inflated_unboundedly(monkeypatch):
    monkeypatch.setattr('congress_api.transport.document_probe.pace_request', lambda url: None)
    stream = CountingStream()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,
            headers={'Content-Encoding': 'gzip', 'Content-Type': 'text/html'}, stream=stream))) as client:
        result = get_prefix('https://x.test/', client=client)
    assert not result.complete and result.content.body_bytes() == b''
    assert stream.reads == 0 and stream.closed
