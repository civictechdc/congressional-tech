"""Native files stay on disk through retention; receipts keep exact source bytes."""
from pathlib import Path
import threading

import pytest

from congress_api.retention.body_files import CapturedFile, content_bytes
from congress_api.retention.capture_inspection import inspect_capture
from congress_api.transport.rust_fetch import RustFetcher, RustResponse
from testing_fakes import MemoryStore, response


PDF = b'%PDF-1.7\n\xff\nfixture\n%%EOF'
URL = 'https://example.gov/statement.pdf'


class FileStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.file_uploads = []

    def put_file(self, key, path):
        self.file_uploads.append(key)
        if key in self.objects:
            return False
        self.objects[key] = Path(path).read_bytes()
        self.writes.append(key)
        return True

    def read_file(self, key, path, *, max_bytes):
        data = self.objects[key]
        assert len(data) <= max_bytes
        Path(path).write_bytes(data)


def native(tmp_path, body=PDF, media='application/pdf', status=200):
    fetcher = RustFetcher.__new__(RustFetcher)
    fetcher.max_bytes = max(len(body), 1024)
    paths = []
    lock = threading.Lock()

    def request(url, transport, **kwargs):
        assert transport == 'direct'
        with lock:
            path = tmp_path / f'{len(paths)}.body'
            paths.append(path)
        path.write_bytes(body)
        return RustResponse(dict(body_file=str(path), http_status=status,
            final_url=url, complete=True,
            response_header_items=[{'name': 'Content-Type', 'value': media}]), tmp_path)

    fetcher._request = request
    return fetcher, paths


def test_pdf_fetch_does_not_materialize_native_body(tmp_path, monkeypatch):
    fetcher, paths = native(tmp_path)
    monkeypatch.setattr(RustResponse, 'iter_content', lambda *a, **k: pytest.fail('Whole body buffered'))
    result, inspection = fetcher.fetch_spooled(URL, before_read=lambda: None)
    body = result['content']['body']
    assert isinstance(body, CapturedFile)
    assert inspection == ('saved', [])
    assert paths[0].exists()
    assert content_bytes(result['content']) == PDF
    body.close()
    assert not paths[0].exists()


def test_normal_file_metadata_skips_large_pdf_reader(tmp_path, monkeypatch):
    from congress_api.retention import capture_metadata
    path = tmp_path / 'large.pdf'
    with path.open('wb') as source:
        source.write(b'%PDF-1.7\n')
        source.truncate(capture_metadata.BODY_LIMIT + 1)
    monkeypatch.setattr(capture_metadata, 'inspect_pdf_file',
                        lambda *a: pytest.fail('Normal capture invoked large-PDF reader'))
    assert capture_metadata.read_document_file(path, 'body-key', 'fingerprint', large_pdf=False) == {
        'body_key': 'body-key', 'parser_fingerprint': 'fingerprint',
        'status': 'size_limit', 'error_type': None,
    }


@pytest.mark.parametrize('body,media,status', [
    (PDF, 'application/pdf', 200),
    (b'%PDF-1.7\npartial', 'application/pdf', 200),
    (b'<html><title>Just a moment</title></html>', 'application/pdf', 200),
    (b'<html><a href="a.pdf">Statement</a></html>', 'text/html', 200),
    (b'refused', 'text/plain', 403),
    (b'', 'text/plain', 200),
])
def test_file_and_byte_inspection_agree(tmp_path, body, media, status):
    path = tmp_path / 'body'
    path.write_bytes(body)
    original = response(URL, body, media, status)
    file = CapturedFile(path, media)
    acquired = {**original, 'content': file.source_dict()}
    assert inspect_capture(acquired) == inspect_capture(original)
    assert file.body_encoding == original['content']['body_encoding']
    assert file.sha256 == original['content']['sha256']


@pytest.mark.parametrize('suffix', [b'\xe2\x82\xac', b'\xe2\x82'])
def test_file_encoding_checks_utf8_across_chunk_boundaries(tmp_path, suffix):
    data = b'a' * (1024**2 - 1) + suffix
    path = tmp_path / 'body'
    path.write_bytes(data)
    file = CapturedFile(path, 'text/plain')
    expected = response(URL, data, 'text/plain')['content']
    assert file.body_encoding == expected['body_encoding']
    assert file.sha256 == expected['sha256']


@pytest.mark.parametrize('field', ['sha256', 'media_type', 'body_encoding'])
def test_file_metadata_cannot_be_relabelled(tmp_path, field):
    fetcher, paths = native(tmp_path)
    capture, _ = fetcher.fetch_spooled(URL, before_read=lambda: None)
    capture['content'][field] = 'changed'
    try:
        with pytest.raises(ValueError, match='metadata mismatch'):
            inspect_capture(capture)
    finally:
        capture['content']['body'].close()


@pytest.mark.parametrize('office', [False, True])
def test_file_archive_separation_preserves_members_and_links(tmp_path, office):
    from congress_api.retention.raw_archive import prepare_capture
    from test_archive_members import archive
    entries = [('testimony.pdf', PDF), ('index.html', b'<a href="https://example.gov/other.pdf">File</a>')]
    if office:
        entries.append(('[Content_Types].xml', b'<Types/>'))
    data = archive(entries)
    original = response(URL + '.zip', data, 'application/zip')
    path = tmp_path / 'archive.body'; path.write_bytes(data)
    file = CapturedFile(path, 'application/zip')
    acquired = {**original, 'content': file.source_dict()}
    before = prepare_capture(original, outcome='saved', links=[])
    after = prepare_capture(acquired, outcome='saved', links=[])
    assert before[:2] == after[:2] and before[3] == after[3]
    assert before[2] == {key: value.read_bytes() if isinstance(value, CapturedFile) else value
                         for key, value in after[2].items()}
    file.close()
