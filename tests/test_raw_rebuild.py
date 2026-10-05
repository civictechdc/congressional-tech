"""Rebuild from retained evidence, without acquiring or rewinding capture state."""
from catalog_test_helpers import selected_path
import gzip
import json
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, CAPTURES_KEY, STATE_KEY, encode_table
from congress_api.retention.raw_catalog import rebuild_catalog, FILENAMES, DOCUMENTS
from test_raw_source_sync import MemoryStore
from test_raw_catalog import table, initialize


def retain(store, record, *, family, source_file, url=None, body=None, pointer=None):
    key = f'receipts/{family}/fixture-{len(store.objects)}.jsonl.gz'
    store.objects[key] = gzip.compress((json.dumps({'record': record}) + '\n').encode())
    body_key = None
    if body is not None:
        digest = sha256(body).hexdigest()
        body_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        store.objects[body_key] = gzip.compress(body)
    row = dict(family=family, source_file=source_file, receipt_key=key, receipt_line=1,
               context_url=url, body_key=body_key, http_status=200 if body else None,
               pointer_json=json.dumps(pointer or []))
    captures = table(store, CAPTURES_KEY).to_pylist()
    store.objects[CAPTURES_KEY] = encode_table(pa.Table.from_pylist([*captures, row], schema=CAPTURE_SCHEMA))
    return key


def test_replay_migration_receipts_and_native_house_xml_without_bootstrap():
    store = MemoryStore()
    url = 'https://publisher.gov/opaque.pdf'
    retain(store, {'eventId': 1, 'congress': 119, 'chamber': 'House',
                   'meetingDocuments': [{'url': url, 'documentType': 'Support Document', 'name': 'Original label'}]},
           family='congress/meetings', source_file='meeting.json')
    xml = f'<witness-list meeting-id="HMKP1"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><description>Literal testimony</description><files><file doc-url="{url}" doc-type="PDF" add-date="2026-01-02"/></files></witness-document></witness-documents></witness></panel></witness-list>'.encode()
    receipt = retain(store, {}, family='house/witness-xml', source_file='witness.xml',
                     url='https://docs.house.gov/1.xml', body=xml)
    rebuild_catalog(store, table(store, CAPTURES_KEY), workers=1)
    row = next(r for r in table(store).to_pylist() if r['source_url'] == url)
    assert row['source_document_type'] == ['Support Document', 'WS']
    assert row['source_document_type_basis'] == ['publisher']
    assert row['source_document_label'] == ['Literal testimony', 'Original label']
    assert row['source_document_added_at'] == ['2026-01-02']
    assert row['source_witness_name'] == ['Jane Doe']
    assert any(o['source_receipt_key'] == [receipt] and o['source_document_type'] == ['WS']
               for o in row['source_occurrences'])


def test_unchanged_capture_replays_current_senate_interpretation(tmp_path):
    store = initialize(tmp_path)
    page = 'https://www.foreign.senate.gov/hearings/example'
    url = 'https://www.foreign.senate.gov/opaque.pdf'
    retain(store, {}, family='senate/pages', source_file='page.html', url=page,
           body=b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>')
    # A previous interpretation and cursor must not suppress source replay.
    index.write_filename_metadata(tmp_path, [dict(body_key=None, filename='opaque.pdf', source_url=url,
        source_document_type=['other'], source_document_type_basis=['senate_parser_fallback'])], workers=1,
        metadata={'raw_capture_rows': '1'})
    for key in (FILENAMES, DOCUMENTS):
        store.objects[key] = selected_path(tmp_path / key).read_bytes()
    rebuild_catalog(store, table(store, CAPTURES_KEY), workers=1)
    row = next(r for r in table(store).to_pylist() if r['source_url'] == url)
    assert row['document_kind'] == ['transcript']
    assert 'other' not in row['source_document_type']


def test_legacy_remote_only_facts_are_archived_without_inventing_native_basis(tmp_path):
    store = initialize(tmp_path)
    index.write_filename_metadata(tmp_path, [dict(body_key=None, filename='opaque.pdf',
        source_url='https://example.gov/opaque.pdf', source_document_type=['witness statement'],
        source_document_label=['witness statement: Jane Doe'])], workers=1)
    for key in (FILENAMES, DOCUMENTS):
        store.objects[key] = selected_path(tmp_path / key).read_bytes()
    # Older tables did not distinguish filename classification from context.
    legacy = table(store).drop(['document_kind_source'])
    store.objects[FILENAMES] = encode_table(legacy)
    before = store.objects[FILENAMES]
    result = rebuild_catalog(store, table(store, CAPTURES_KEY), workers=1)
    assert store.objects[result['previous_filenames_key']] == before
    row, = table(store).to_pylist()
    assert row.get('source_document_type') is None
    assert row.get('document_kind') is None


def test_rebuild_only_cli_skips_acquisition_and_preserves_newer_state(tmp_path, monkeypatch):
    from congress_api.cli import raw_sync
    store = initialize(tmp_path)
    store.objects[STATE_KEY] = b'newer download state'
    # Include a capture absent from the old derived tables.
    retain(store, {'url': 'https://example.gov/new.pdf'}, family='documents', source_file='receipts.jsonl',
           url='https://example.gov/new.pdf', body=b'%PDF-1.7\n%%EOF')
    before = {k: v for k, v in store.objects.items() if k not in (FILENAMES, DOCUMENTS)}
    def forbidden(*a, **kw):
        pytest.fail('rebuild-only entered acquisition')
    monkeypatch.setattr(raw_sync, 'Archive', forbidden)
    monkeypatch.setattr(raw_sync, 'RustFetcher', forbidden)
    monkeypatch.setattr(raw_sync.zyte, 'token', forbidden)
    monkeypatch.setattr(raw_sync, 'seed_files', forbidden)
    monkeypatch.setattr(raw_sync, 'R2Store', lambda *a: store)
    import boto3
    monkeypatch.setattr(boto3, 'client', lambda *a, **kw: object())
    for name in ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(name, 'test')
    summary = tmp_path / 'summary.json'
    raw_sync.main(['--rebuild-only', '--index-workers', '1', '--summary', str(summary)])
    assert all(store.objects[k] == v for k, v in before.items())
    assert not any(k in {CAPTURES_KEY, STATE_KEY} or k.startswith(('bodies/', 'receipts/')) for k in store.writes)
    assert any(r['filename'] == 'new.pdf' for r in table(store).to_pylist())
    assert json.loads(summary.read_text())['mode'] == 'rebuild'


def test_paired_validation_rejects_mismatched_catalog_before_writes(tmp_path, monkeypatch):
    store = initialize(tmp_path)
    original = index.write_filename_metadata
    def corrupt(root, *a, **kw):
        result = original(root, *a, **kw)
        path = root / DOCUMENTS
        doc = pq.read_table(path)
        pq.write_table(doc.replace_schema_metadata({**doc.schema.metadata, b'catalog_id': b'wrong'}), path)
        return result
    monkeypatch.setattr(index, 'write_filename_metadata', corrupt)
    with pytest.raises(ValueError, match='catalog_id'):
        rebuild_catalog(store, table(store, CAPTURES_KEY), workers=1)
    assert all(key.startswith("indexes/processing/") for key in store.writes)


def test_retained_house_labels_are_inferences_and_native_unknown_stays_null():
    context = index.DocumentSources()
    url = 'https://example.gov/opaque.pdf'
    context.add_house({'1': {'documents': [['witness statement', 'witness statement: Jane Doe', url, []]]}},
                      index.context_values(source_receipt_key='retained-house-state', source_receipt_line=7))
    row = context.for_url(url)
    assert row['source_document_type_basis'] == ['house_parser_inference']
    assert row['source_document_label'] == ['witness statement: Jane Doe']
    context.add_house_evidence({'document_groups': [{'active': True, 'source': 'meeting_xml',
        'description': 'Unlabelled file', 'files': [{'active': True, 'url': url + '?unknown'}]}]})
    unknown = context.for_url(url + '?unknown')
    assert 'source_document_type' not in unknown and 'source_document_type_basis' not in unknown


def test_new_capture_state_written_during_rebuild_survives(tmp_path, monkeypatch):
    store = initialize(tmp_path)
    original = index.write_filename_metadata
    def concurrent_capture(*a, **kw):
        retain(store, {}, family='documents', source_file='later.json',
               url='https://example.gov/later.pdf', body=b'%PDF-1.7\n%%EOF')
        store.objects[STATE_KEY] = b'later download state'
        return original(*a, **kw)
    monkeypatch.setattr(index, 'write_filename_metadata', concurrent_capture)
    rebuild_catalog(store, workers=1)
    assert len(table(store, CAPTURES_KEY)) == 1
    assert store.objects[STATE_KEY] == b'later download state'
    assert table(store).schema.metadata[b'raw_capture_rows'] == b'0'
    assert all(k not in {CAPTURES_KEY, STATE_KEY} for k in store.writes)


def test_history_failure_prevents_either_table_replacement(tmp_path):
    store = initialize(tmp_path)
    before = dict(store.objects)
    original = store.put
    def fail(key, *a, **kw):
        if key.startswith('catalog-history/'):
            raise OSError('history unavailable')
        return original(key, *a, **kw)
    store.put = fail
    with pytest.raises(OSError, match='history unavailable'):
        rebuild_catalog(store, workers=1)
    assert {k: v for k, v in store.objects.items() if not k.startswith("indexes/processing/")} == before


def test_capture_locator_is_kept_alongside_parent_context():
    store = MemoryStore()
    url = 'https://example.gov/opaque.pdf'
    retain(store, {'eventId': 1, 'congress': 119, 'chamber': 'House',
                   'meetingDocuments': [{'url': url, 'documentType': 'Witness Statement'}]},
           family='congress/meetings', source_file='meeting.json')
    receipt = retain(store, {'url': url}, family='documents', source_file='capture.json',
                     url=url, body=b'%PDF-1.7\n%%EOF')
    rebuild_catalog(store, workers=1)
    row, = table(store).to_pylist()
    assert any(o['source_receipt_key'] == [receipt] and o['source_occurrence_scope'] == ['capture']
               for o in row['source_occurrences'])
    assert row['source_document_type'] == ['Witness Statement']


def test_saved_senate_state_replays_newly_recognized_links_from_exact_body():
    store = MemoryStore()
    page = 'https://www.foreign.senate.gov/hearings/example'
    body = b'<html><h2>Hearing Transcript</h2><a href="/opaque.pdf">Download</a></html>'
    digest = sha256(body).hexdigest()
    store.objects[f'bodies/sha256/{digest[:2]}/{digest}.gz'] = gzip.compress(body)
    retain(store, {'foreign.senate.gov': {'pages': {page: {
        'documents': [], 'cache_replay': {'raw_sha256': digest}}}}},
           family='senate/pages', source_file='state/senate.json.gz')
    rebuild_catalog(store, workers=1)
    row = next(r for r in table(store).to_pylist()
               if r['source_url'] == 'https://www.foreign.senate.gov/opaque.pdf')
    assert row['document_kind'] == ['transcript']
    assert row['source_page_sha256'] == [digest]


def test_receipt_replay_does_not_materialize_all_capture_payloads():
    import tracemalloc

    # All capture fields remain available to the caller, but only receipt
    # locators are needed before the corresponding receipt line is reached.
    count = 5000
    captures = pa.table({
        'receipt_key': ['receipt'] * count,
        'receipt_line': list(range(1, count + 1)),
        'context_url': ['https://example.gov/' + 'x' * 8192] * count,
    })
    payload = gzip.compress(b'{"record":{"id":1}}\n')
    tracemalloc.start()
    records = index.retained_records(captures, lambda _: payload)
    try:
        record, rows, locator = next(records)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        records.close()
        tracemalloc.stop()
    assert record == {'id': 1}
    assert rows == captures.slice(0, 1).to_pylist()
    assert locator['source_receipt_line'] == {'1'}
    assert peak < 8 * 1024**2, 'Keep receipt positions, not every decoded capture row'


def test_receipt_replay_groups_noncontiguous_rows_without_losing_fields():
    captures = pa.table({
        'receipt_key': ['b', 'a', 'a', 'b', 'a'],
        'receipt_line': [2, 2, 1, 1, 2],
        'body_key': ['b2', 'a2-first', 'a1', 'b1', 'a2-last'],
    })
    captures = pa.Table.from_batches(captures.to_batches(max_chunksize=2))
    payload = gzip.compress(b'{"record":{"id":1}}\n{"record":{"id":2}}\n')
    result = list(index.retained_records(captures, lambda _: payload))
    assert [(r['id'], loc['source_receipt_key'], [row['body_key'] for row in rows])
            for r, rows, loc in result] == [
        (1, {'a'}, ['a1']), (2, {'a'}, ['a2-first', 'a2-last']),
        (1, {'b'}, ['b1']), (2, {'b'}, ['b2']),
    ]


def test_rebuild_releases_capture_index_before_filename_interpretation(tmp_path, monkeypatch):
    import gc
    import weakref
    from congress_api.retention import raw_catalog

    store = initialize(tmp_path)
    retain(store, {'url': 'https://example.gov/new.pdf'}, family='documents',
           source_file='capture.json', url='https://example.gov/new.pdf', body=b'%PDF-1.7\n%%EOF')
    decoded_captures = []
    original_decode = raw_catalog.decode_table
    original_write = index.write_filename_metadata

    def decode(data):
        result = original_decode(data)
        if result.schema.remove_metadata() == CAPTURE_SCHEMA:
            decoded_captures.append(weakref.ref(result))
        return result

    def write(*args, **kwargs):
        gc.collect()
        assert decoded_captures and all(ref() is None for ref in decoded_captures), (
            'Receipt replay is complete; do not retain the capture index during PDF inspection'
        )
        return original_write(*args, **kwargs)

    monkeypatch.setattr(raw_catalog, 'decode_table', decode)
    monkeypatch.setattr(index, 'write_filename_metadata', write)
    rebuild_catalog(store, workers=1)
    assert table(store).schema.metadata[b'raw_capture_rows'] == b'1'


def test_embedded_house_html_keeps_source_role_and_observed_format():
    store = MemoryStore()
    retain(store, {'evidence': {'html': {}}}, family='house/meeting-xml',
           source_file='state/house.json.gz', pointer=['evidence', 'html'],
           body=b'<html><title>Committee meeting</title></html>')
    rebuild_catalog(store, workers=1, inspect_bodies=True)
    row, = table(store).to_pylist()
    assert row['source_record_type'] == ['committee-meeting-page']
    assert row['record_role'] == ['source-record']
    assert row['body_format'] == ['html']


def test_capture_role_requires_one_matching_receipt_and_pointer(tmp_path):
    source = dict(body_key=None, filename='opaque.html', source_url='https://example.gov/opaque.html',
        source_occurrences=[
            {'source_occurrence_scope': ['capture'], 'source_receipt_key': ['receipts/house/meeting-xml/day/run.jsonl.gz'],
             'source_capture_pointer': ['[]']},
            {'source_occurrence_scope': ['capture'], 'source_receipt_key': ['receipts/documents/day/run.jsonl.gz'],
             'source_capture_pointer': ['["evidence", "html"]']},
        ])
    (tmp_path / 'indexes').mkdir()
    index.write_filename_metadata(tmp_path, [source], workers=1)
    row, = pq.read_table(selected_path(tmp_path / FILENAMES)).to_pylist()
    assert row['record_role'] == ['document']
    assert row.get('source_record_type') is None


def test_capture_state_is_released_and_summary_saved_before_rebuild(tmp_path, monkeypatch):
    import gc
    import signal
    import weakref
    import boto3
    from congress_api.cli import raw_sync
    references = []
    class Collection:
        def __init__(self, store, *_args, **_kwargs):
            self.store = store
            references.append(weakref.ref(self))
    class Fetcher:
        sequence = 2
        file_dispatches = 1
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def fetch_spooled(self, _url, **_kwargs): pytest.fail('No real network in this test')
    class Store:
        def __init__(self, *_args, **_kwargs): pass
        def put(self, *_args): pass
    summary = tmp_path / 'summary.json'
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def rebuild(*_args, **_kwargs):
        gc.collect()
        assert references[0]() is None, 'Acquisition state remains live during the catalog join'
        assert {sig: signal.getsignal(sig) for sig in handlers} == handlers
        saved = json.loads(summary.read_text())
        assert saved['attempted'] == 2 and saved['catalog_status'] == 'running'
        raise OSError('catalog interrupted')
    monkeypatch.setattr(raw_sync, 'Archive', Collection)
    monkeypatch.setattr(raw_sync, 'RustFetcher', Fetcher)
    monkeypatch.setattr(raw_sync, 'R2Store', Store)
    monkeypatch.setattr(raw_sync, 'run_sync', lambda *a, **k: {'attempted': 2})
    monkeypatch.setattr(raw_sync, 'rebuild_catalog', rebuild)
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: object())
    for key in ('CLOUDFLARE_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(key, 'fixture')
    with pytest.raises(OSError, match='catalog interrupted'):
        raw_sync.main(['--transport', 'direct', '--summary', str(summary)])
    saved = json.loads(summary.read_text())
    assert saved['attempted'] == 2
    assert saved['acquisition_status'] == 'completed'
    assert saved['catalog_status'] == 'failed'
    assert saved['error_type'] == 'OSError'
    assert saved['accounting']['native_request_dispatches'] == 2
    assert saved['accounting']['http_request_starts'] is None
    assert json.loads(summary.with_suffix('.progress.json').read_text())['status'] == 'failed'
