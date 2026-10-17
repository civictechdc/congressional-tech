"""Native files stay on disk through retention; receipts keep exact source bytes."""
import gzip
import hashlib
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.body_files import CapturedFile, content_bytes
from congress_api.retention.capture_inspection import inspect_capture
from congress_api.retention.bundles import restore
from congress_api.retention.raw_archive import Archive
from congress_api.transport.rust_fetch import RustFetcher, RustResponse
from test_async_capture import receipts
from test_raw_source_sync import MemoryStore, response


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


def test_general_capture_uses_file_upload_and_restores_exact_receipt(tmp_path):
    fetcher, paths = native(tmp_path)
    store = FileStore()
    stats = run_sync(Archive(store, 'file-backed'), [{'url': URL}],
                     fetch_spooled=fetcher.fetch_spooled, limit=1)
    assert stats['saved'] == 1 and stats['file_body_uploads'] == 1
    assert stats['stage_seconds']['file_retention_seconds'] > 0
    assert len(store.file_uploads) == 1
    receipt, = receipts(store)
    restored = restore(receipt['record'], receipt['captures'],
                       lambda key: gzip.decompress(store.read(key)))
    assert content_bytes(restored['content']) == PDF
    assert receipt['record']['content']['sha256'] == hashlib.sha256(PDF).hexdigest()
    assert not any(path.exists() for path in paths)
    assert not list(tmp_path.glob('*.gz'))


def test_normal_file_capture_preserves_metadata_size_limit(tmp_path):
    from congress_api.retention.capture_metadata import BODY_LIMIT
    data = b'%PDF-1.7\n' + b' ' * BODY_LIMIT + b'\n%%EOF'
    fetcher, paths = native(tmp_path, data)
    store = FileStore()
    stats = run_sync(Archive(store, 'large-file-metadata'), [{'url': URL}],
                     fetch_spooled=fetcher.fetch_spooled, limit=1)
    assert stats['saved'] == 1 and stats['file_body_uploads'] == 1
    assert stats['body_metadata'] == {'size_limit': 1}
    assert not any(path.exists() for path in paths)


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


def test_failed_file_upload_leaves_no_receipt_or_scratch(tmp_path):
    fetcher, paths = native(tmp_path)
    store = FileStore()
    def fail(*args):
        raise OSError('upload interrupted')
    store.put_file = fail
    with pytest.raises(OSError, match='upload interrupted'):
        run_sync(Archive(store, 'failed-file'), [{'url': URL}],
                 fetch_spooled=fetcher.fetch_spooled, limit=1)
    assert not receipts(store)
    assert not any(path.exists() for path in paths)
    assert not list(tmp_path.glob('*.gz'))


@pytest.mark.parametrize('suffix', [b'\xe2\x82\xac', b'\xe2\x82'])
def test_file_encoding_checks_utf8_across_chunk_boundaries(tmp_path, suffix):
    data = b'a' * (1024**2 - 1) + suffix
    path = tmp_path / 'body'
    path.write_bytes(data)
    file = CapturedFile(path, 'text/plain')
    expected = response(URL, data, 'text/plain')['content']
    assert file.body_encoding == expected['body_encoding']
    assert file.sha256 == expected['sha256']


@pytest.mark.parametrize('corrupt', [False, True])
def test_existing_compressed_representation_is_verified(tmp_path, corrupt):
    fetcher, paths = native(tmp_path)
    store = FileStore()
    key = f'bodies/sha256/{hashlib.sha256(PDF).hexdigest()[:2]}/{hashlib.sha256(PDF).hexdigest()}.gz'
    stored = gzip.compress(b'wrong' if corrupt else PDF, compresslevel=9, mtime=123)
    store.objects[key] = stored
    if corrupt:
        with pytest.raises(ValueError, match='checksum'):
            run_sync(Archive(store, 'orphan'), [{'url': URL}], fetch_spooled=fetcher.fetch_spooled)
        assert not receipts(store)
    else:
        run_sync(Archive(store, 'orphan'), [{'url': URL}], fetch_spooled=fetcher.fetch_spooled)
        assert receipts(store)[0]['captures'][0]['stored_sha256'] == hashlib.sha256(stored).hexdigest()
    assert store.objects[key] == stored
    assert not any(path.exists() for path in paths)


def test_changed_file_and_foreign_scratch_are_preserved_or_refused(tmp_path):
    from congress_api.retention.body_files import retain_body_file
    source, scratch = tmp_path / 'source', tmp_path / 'scratch'
    source.write_bytes(PDF)
    body = CapturedFile(source, 'application/pdf')
    source.write_bytes(PDF.replace(b'fixture', b'changed'))
    store = FileStore()
    with pytest.raises(ValueError, match='changed'):
        retain_body_file(store, source, scratch, expected_sha256=body.sha256)
    assert not store.file_uploads and not scratch.exists()
    scratch.write_bytes(b'existing evidence')
    with pytest.raises(FileExistsError):
        retain_body_file(store, source, scratch)
    assert scratch.read_bytes() == b'existing evidence'


def test_disk_reservation_survives_until_upload_and_stop_drains(tmp_path):
    fetcher, paths = native(tmp_path)
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    store = FileStore()
    put = store.put_file
    def blocked(key, path):
        entered.set()
        assert release.wait(5)
        return put(key, path)
    store.put_file = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(run_sync, Archive(store, 'disk-lifetime'),
            [{'url': URL}, {'url': URL + '?second'}], fetch_spooled=fetcher.fetch_spooled,
            workers=2, download_workers=2, max_bytes=1024**2, max_spool_bytes=4*1024**2,
            stop=stop)
        try:
            assert entered.wait(5)
            assert len(paths) == 1 and paths[0].exists()
            assert not receipts(store)
            stop.set()
        finally:
            release.set()
        with pytest.raises(InterruptedError):
            task.result(timeout=10)
    assert len(receipts(store)) == 1
    assert not paths[0].exists()


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


def test_aliases_share_one_file_upload_and_keep_both_receipts(tmp_path):
    fetcher, paths = native(tmp_path)
    store = FileStore()
    stats = run_sync(Archive(store, 'aliases'), [{'url': URL}, {'url': URL + '?alias'}],
                     fetch_spooled=fetcher.fetch_spooled, workers=2, limit=2)
    assert stats['saved'] == 2 and len(store.file_uploads) == 1
    assert len(receipts(store)) == 2 and len(paths) == 2
    assert not any(path.exists() for path in paths)


@pytest.mark.parametrize('provider_status', [200, 401])
def test_file_direct_attempt_and_zyte_evidence_round_trip(tmp_path, monkeypatch, provider_status):
    import base64
    import json
    monkeypatch.setenv('ZYTE_TOKEN', 'fixture')
    fetcher = RustFetcher.__new__(RustFetcher)
    fetcher.max_bytes = 1024
    paths = []
    provider = dict(url=URL, statusCode=200,
        httpResponseBody=base64.b64encode(PDF).decode(),
        httpResponseHeaders=[{'name': 'Content-Type', 'value': 'application/pdf'}])
    def request(url, transport, **kwargs):
        path = tmp_path / f'{len(paths)}.body'; paths.append(path)
        direct = transport == 'direct'
        path.write_bytes(b'blocked' if direct else json.dumps(provider).encode()
                         if provider_status == 200 else b'unauthorized')
        return RustResponse(dict(body_file=str(path), http_status=403 if direct else provider_status,
            final_url=url, complete=True,
            response_header_items=[{'name': 'Content-Type', 'value': 'text/plain' if direct else 'application/json'}]), tmp_path)
    fetcher._request = request
    store = FileStore()
    def run():
        return run_sync(Archive(store, 'zyte-file'), [{'url': URL}],
                        fetch_spooled=fetcher.fetch_spooled, limit=1)
    if provider_status == 401:
        with pytest.raises(RuntimeError, match='authorization'):
            run()
    else:
        assert run()['saved'] == 1
    receipt, = receipts(store)
    restored = restore(receipt['record'], receipt['captures'], lambda key: gzip.decompress(store.read(key)))
    assert content_bytes(restored['prior_attempts'][0]['content']) == b'blocked'
    if provider_status == 200:
        assert content_bytes(restored['content']) == PDF
        assert restored['provider_response'] == provider
    else:
        assert content_bytes(restored['provider_content']) == b'unauthorized'
    assert len(paths) == 2 and not any(path.exists() for path in paths)


def test_cancel_drains_file_readers_and_uploads(tmp_path):
    import asyncio
    from congress_api.acquisition.raw_sync import run_async
    async def check():
        fetcher, paths = native(tmp_path)
        store = FileStore()
        entered, release = threading.Event(), threading.Event()
        put = store.put_file
        def blocked(key, path):
            entered.set()
            assert release.wait(5)
            return put(key, path)
        store.put_file = blocked
        task = asyncio.create_task(run_async(Archive(store, 'cancel-files'), [{'url': URL}],
            fetch_spooled=fetcher.fetch_spooled, workers=1, limit=1))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert paths[0].exists()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert len(receipts(store)) == 1 and not paths[0].exists()
    asyncio.run(check())


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
