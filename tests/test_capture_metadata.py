"""Completed captures retain body readings before publishing resumable receipts."""

from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.raw_sync import run_sync
from congress_api.retention.capture_metadata import CaptureMetadata, MetadataWriter, PREFIX
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import rebuild_catalog
from test_raw_catalog import table
from test_raw_source_sync import MemoryStore, response


PDF = (Path(__file__).parent / 'fixtures/meeting_inventory/senate-burma-hearing-cover.pdf').read_bytes()


def body_key(data):
    digest = sha256(data).hexdigest()
    return f'bodies/sha256/{digest[:2]}/{digest}.gz'


def readings(store):
    return [row for key in store.keys(PREFIX)
            for row in pq.read_table(pa.BufferReader(store.read(key))).to_pylist()]


def test_writer_rotates_without_rewriting_completed_files():
    store = MemoryStore()
    now = [0]
    with MetadataWriter(store, 'stream', max_rows=2, interval=10, clock=lambda: now[0]) as writer:
        writer.append(dict(body_key='a', status='unclassified'))
        assert not store.keys(PREFIX)
        writer.append(dict(body_key='b', status='unclassified'))
        first = {key: store.read(key) for key in store.keys(PREFIX)}
        assert len(first) == 1
        writer.append(dict(body_key='c', status='unclassified'))
        now[0] = 10
        writer.flush_due()
        assert all(store.read(key) == value for key, value in first.items())
    assert [r['body_key'] for r in readings(store)] == ['a', 'b', 'c']
    assert len(store.keys(PREFIX)) == 2


def test_capture_metadata_is_reused_across_runs_including_empty_results():
    store = MemoryStore()
    calls = []

    def inspect(data):
        calls.append(data)
        return {}

    for run in ('first', 'resumed'):
        with CaptureMetadata(store, run, inspect=inspect) as metadata:
            metadata.record(b'body', body_key(b'body'))
            metadata.record(b'body', body_key(b'body'))
    assert calls == [b'body']
    assert {r['status'] for r in readings(store)} == {'unclassified'}
    assert all(r['parser_fingerprint'] for r in readings(store))


def test_capture_then_update_uses_cover_without_reading_body_from_storage():
    class NoBodyReads(MemoryStore):
        def read(self, key):
            assert not key.startswith('bodies/'), 'Fresh extraction must be reused'
            return super().read(key)

    store = NoBodyReads()
    rebuild_catalog(store, workers=1)
    url = 'https://example.gov/opaque.pdf'
    run_sync(Archive(store, 'capture'), [{'url': url}],
             fetch=lambda u: response(u, PDF), limit=1)
    rows = readings(store)
    assert any(r['content_citation'] == ['S. Hrg. 117-16'] for r in rows)
    metadata_write = next(i for i, key in enumerate(store.writes) if key.startswith(PREFIX))
    receipt_write = next(i for i, key in enumerate(store.writes) if key.startswith('receipts/'))
    assert metadata_write < receipt_write
    result = rebuild_catalog(store, workers=1)
    assert result['rows'] == 1
    row, = table(store).to_pylist()
    assert row['document_kind'] == ['published-hearing']
    assert row['content_citation'] == ['S. Hrg. 117-16']


def test_metadata_failure_cannot_publish_a_completed_capture_receipt():
    class FailedMetadata(MemoryStore):
        def put(self, key, data, *, immutable=False):
            if key.startswith(PREFIX):
                raise OSError('metadata storage unavailable')
            return super().put(key, data, immutable=immutable)

    store = FailedMetadata()
    with pytest.raises(OSError, match='metadata storage unavailable'):
        run_sync(Archive(store, 'failed'), [{'url': 'https://example.gov/a.pdf'}],
                 fetch=lambda u: response(u, PDF), limit=1)
    assert store.keys('bodies/')
    assert not store.keys('receipts/')


def test_extraction_failure_retains_bytes_and_records_failure():
    store = MemoryStore()

    def broken(data):
        raise ValueError('bad document')

    with CaptureMetadata(store, 'failed-reader', inspect=broken) as metadata:
        metadata.record(b'body', body_key(b'body'))
    row, = readings(store)
    assert row['status'] == 'failed' and row['error_type'] == 'ValueError'


def test_writer_retries_the_same_closed_part_after_an_uncertain_upload():
    class UncertainUpload(MemoryStore):
        uncertain = True

        def put(self, key, data, *, immutable=False):
            super().put(key, data, immutable=immutable)
            if key.startswith(PREFIX) and self.uncertain:
                self.uncertain = False
                raise OSError('response lost after upload')

    store = UncertainUpload()
    with MetadataWriter(store, 'retry', max_rows=1) as writer:
        with pytest.raises(OSError, match='response lost'):
            writer.append(dict(body_key='a', status='unclassified'))
        writer.flush()
        writer.append(dict(body_key='b', status='unclassified'))
    assert [r['body_key'] for r in readings(store)] == ['a', 'b']
    assert len(store.keys(PREFIX)) == 2


def test_metadata_survives_interrupted_index_publication():
    class FailedIndex(MemoryStore):
        fail = True

        def put(self, key, data, *, immutable=False):
            if key == 'indexes/download-state.parquet' and self.fail:
                self.fail = False
                raise OSError('interrupted before state upload')
            return super().put(key, data, immutable=immutable)

    store = FailedIndex()
    url = 'https://example.gov/opaque.pdf'
    with pytest.raises(OSError, match='interrupted'):
        run_sync(Archive(store, 'interrupted'), [{'url': url}],
                 fetch=lambda u: response(u, PDF), limit=1)
    assert store.keys(PREFIX) and store.keys('receipts/')
    result = run_sync(Archive(store, 'resume'), [{'url': url}],
                      fetch=lambda _: pytest.fail('Completed capture was refetched'), limit=1)
    assert result['attempted'] == 0
    rebuild_catalog(store, workers=1)
    assert table(store).to_pylist()[0]['content_citation'] == ['S. Hrg. 117-16']


def test_saved_metadata_survives_reader_changes_until_explicit_inspection(tmp_path):
    from congress_api.retention.document_index import write_filename_metadata
    from catalog_test_helpers import selected_path

    store = MemoryStore()
    key = body_key(PDF)
    with MetadataWriter(store, 'old-reader') as writer:
        writer.append(dict(body_key=key, parser_fingerprint='earlier-reader', status='completed',
                           body_format=['pdf'], content_citation=['old reading'],
                           content_document_kind=['published-hearing']))
    calls = []

    def read_body(key):
        calls.append(key)
        return PDF

    source = dict(body_key=key, filename='opaque.pdf', source_url='https://example.gov/opaque.pdf')
    for repair, expected in [(False, 'old reading'), (True, 'S. Hrg. 117-16')]:
        write_filename_metadata(tmp_path, [source], workers=1, cache_store=store,
                                read_body=read_body, reuse_results=not repair, inspect_bodies=repair)
        row, = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
        assert row['content_citation'] == [expected]
        assert bool(calls) == repair


def test_body_facts_reach_all_aliases_without_sharing_http_failure():
    store = MemoryStore()
    good, bad = 'https://example.gov/good.pdf', 'https://example.gov/bad.pdf'
    result = run_sync(Archive(store, 'aliases'), [{'url': good}, {'url': bad}],
                      fetch=lambda u: response(u, PDF, status=200 if u == good else 503), limit=2)
    assert result['body_metadata'] == {'completed': 1, 'reused': 1}
    assert len(readings(store)) == 1
    rebuild_catalog(store, workers=1)
    rows = {row['source_url']: row for row in table(store).to_pylist()}
    assert rows[good]['record_role'] == ['document']
    assert rows[bad]['record_role'] == ['error-response']
    assert rows[good]['content_citation'] == ['S. Hrg. 117-16']


def test_invalid_pdf_records_reader_failure_without_losing_capture():
    store = MemoryStore()
    url = 'https://example.gov/damaged.pdf'
    result = run_sync(Archive(store, 'damaged'), [{'url': url}],
                      fetch=lambda u: response(u, b'%PDF-1.7\ninvalid\n%%EOF'), limit=1)
    assert result['body_metadata']['failed'] == 1
    row, = readings(store)
    assert row['status'] == 'failed' and row['error_type']
    assert row['body_format'] == ['pdf']
    assert Archive(store, 'read').state[url]['body_key'] == row['body_key']


def test_byte_limit_rotates_before_row_limit_and_retains_partial_final_part():
    store = MemoryStore()
    with MetadataWriter(store, 'bytes', max_rows=1000, max_bytes=100) as writer:
        writer.append(dict(body_key='a', status='completed', source_record_identifier=['x' * 100]))
        assert len(store.keys(PREFIX)) == 1
        writer.append(dict(body_key='b', status='unclassified'))
    assert len(readings(store)) == 2


def test_slow_upload_bounds_completed_responses_and_does_not_block_on_slow_request():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    uploading, release, third_started = Event(), Event(), Event()
    calls, guard = [], Lock()

    class SlowUpload(MemoryStore):
        def put(self, key, data, *, immutable=False):
            if key.startswith('bodies/') and not uploading.is_set():
                uploading.set()
                assert release.wait(5), 'Test did not release the upload'
            return super().put(key, data, immutable=immutable)

    def fetch(url):
        with guard:
            calls.append(url)
        if url.endswith('0.pdf'):
            assert third_started.wait(5), 'A slow request blocked the next download'
        if url.endswith('2.pdf'):
            third_started.set()
        return response(url, PDF)

    store = SlowUpload()
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run_sync, Archive(store, 'bounded'),
                           [{'url': f'https://example.gov/{n}.pdf'} for n in range(5)],
                           fetch=fetch, workers=2, limit=5)
        try:
            assert uploading.wait(5)
            assert len(calls) == 2, 'The fetch queue grew while storage was blocked'
        finally:
            release.set()
        result = task.result(timeout=10)
    assert result['saved'] == 5
    assert result['body_metadata'] == {'completed': 1, 'reused': 4}


def test_earlier_part_schema_with_fewer_optional_fields_remains_readable():
    from congress_api.retention.capture_metadata import restore_body_results

    store = MemoryStore()
    schema = pa.schema([(name, pa.string()) for name in
                        ('body_key', 'parser_fingerprint', 'status', 'error_type')]
                       + [('body_format', pa.list_(pa.string()))], metadata={'format_version': '1'})
    stream = pa.BufferOutputStream()
    pq.write_table(pa.Table.from_pylist([dict(body_key='old-body', parser_fingerprint='old-reader',
                                            status='completed', body_format=['pdf'])], schema=schema), stream)
    store.put(PREFIX + 'earlier/part.parquet', stream.getvalue().to_pybytes(), immutable=True)
    cache = {}
    restore_body_results(store, cache)
    assert cache[('document', 'old-body')] == {'body_format': ['pdf']}
    with CaptureMetadata(store, 'new-reader', inspect=lambda _: pytest.fail('Earlier result was discarded')) as metadata:
        metadata.record(b'old bytes', 'old-body')


@pytest.mark.parametrize('kind', ['pdf', 'xml'])
def test_explicit_negative_result_is_not_replaced_by_old_capture_reading(tmp_path, kind):
    from io import BytesIO
    from pypdf import PdfWriter
    from congress_api.retention.document_index import write_filename_metadata
    from catalog_test_helpers import selected_path

    pdf = PdfWriter()
    pdf.add_blank_page(width=612, height=792)
    output = BytesIO()
    pdf.write(output)
    data = output.getvalue() if kind == 'pdf' else b'<bill/>'
    key = body_key(data)
    store = MemoryStore()
    with MetadataWriter(store, 'earlier') as writer:
        writer.append(dict(body_key=key, parser_fingerprint='earlier-reader', status='completed',
                           body_format=[kind], content_document_kind=['published-hearing'],
                           content_citation=['incorrect previous reading']))
    source = dict(body_key=key, filename=f'opaque.{kind}', source_url=f'https://example.gov/opaque.{kind}')
    write_filename_metadata(tmp_path, [source], workers=1, cache_store=store,
                            reuse_results=False, inspect_bodies=True, read_body=lambda _: data)
    previous = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet'))
    alias = {**source, 'source_url': 'https://example.gov/alias.pdf'}
    write_filename_metadata(tmp_path, [source, alias], workers=1, cache_store=store,
                            previous=previous, read_body=lambda _: pytest.fail('Unexpected body read'))
    for row in pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist():
        assert row['document_kind'] is None
        assert not row.get('content_citation')


def test_capture_preserves_completed_legacy_readings():
    from congress_api.retention.catalog_cache import save_results

    store = MemoryStore()
    key = body_key(PDF)
    save_results(store, 'bodies', 'earlier-reader', ('reader', 'body_key'), {('cover', key): {}})
    with CaptureMetadata(store, 'reuse-legacy', inspect=lambda _: pytest.fail('Legacy reading was repeated')) as metadata:
        metadata.record(PDF, key)
        assert metadata.counts == {'reused': 1}
    assert not store.keys(PREFIX)


def test_oversized_body_retains_deferred_inspection_status():
    from congress_api.retention.capture_metadata import BODY_LIMIT

    store = MemoryStore()
    data = b'x' * (BODY_LIMIT + 1)
    with CaptureMetadata(store, 'size-limit', inspect=lambda _: pytest.fail('Oversized body was inspected')) as metadata:
        metadata.record(data, body_key(data))
    row, = readings(store)
    assert row['status'] == 'size_limit'
    assert row['content_document_kind'] is None
