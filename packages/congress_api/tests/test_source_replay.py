"""Raw changes replay complete retained receipt owners with maintained policy."""
from contextlib import closing
from copy import deepcopy

import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.document_evidence import read_retained_body
from congress_api.retention.raw_archive import CAPTURES_KEY, decode_table
from congress_api.retention.raw_storage import RawStorage
from congress_api.retention.source_observations import SourceObservationStorage, SourceObservationTrace
from congress_api.retention.source_replay import prepare_source_replay
from testing_fakes import MemoryNative
from testing_fakes import SelectorStore
from test_raw_rebuild import retain


def test_new_ambiguous_meeting_replays_exact_old_xml_and_source_owners(tmp_path, monkeypatch):
    class RawNative(MemoryNative):
        def run_table(self, table, **request):
            pin = super().run_table(table, **request)
            return dict(pin, id='initial', verified=True, dataset=dict(version='initial', groups=dict(source=dict(rows=len(table)))))
    native, store = RawNative(), SelectorStore()
    raw = RawStorage(store, native, max_capture_rows=2)
    retain(store, dict(eventId=7, congress=119, chamber='House', committees=[dict(systemCode='hsii00')]),
           family='congress/meetings', source_file='meeting.json')
    retain(store, {}, family='house/witness-xml', source_file='witness.xml', url='https://docs.house.gov/7.xml',
        body=b'<witness-list meeting-id="HMKP7"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><files><file doc-url="https://example.gov/paper.pdf" doc-type="PDF"/></files></witness-document></witness-documents></witness></panel></witness-list>')
    initial_rows = decode_table(store.read(CAPTURES_KEY))
    empty = raw.snapshot()
    selected = raw.publish(raw.prepare(empty, operation='initial', captures=initial_rows))
    owner = SourceObservationStorage(native=native, store=store, namespace='replay-owners', max_rows=64, max_bytes=1 << 20)
    read_body = lambda key: read_retained_body(None, key, read_compressed=store.read)
    with prepare_source_replay(store, snapshot=selected, changes=selected.changes_since(empty.identity),
            observations=owner, root=None, directory=tmp_path / 'initial', read_body=read_body) as prepared:
        old = {index.source_identity(row): deepcopy(row) for row in prepared.sources()}
        before = prepared.after
    paper = next(row for row in old.values() if row['source_url'] == 'https://example.gov/paper.pdf')
    assert paper['source_committee_code'] == ['hsii00']
    # Add a second House Congress for the same event: the unscoped XML lookup
    # becomes ambiguous. The old XML receipt must replay to remove inherited facts.
    retain(store, dict(eventId=7, congress=118, chamber='House', committees=[dict(systemCode='hsju00')]),
           family='congress/meetings', source_file='other-meeting.json')
    new_rows = decode_table(store.read(CAPTURES_KEY)).slice(len(initial_rows))
    current = raw.publish(raw.prepare(selected, operation='another-congress', captures=new_rows))
    monkeypatch.setattr(current, 'captures', lambda: (_ for _ in ()).throw(AssertionError('Global raw scan')))
    with prepare_source_replay(store, snapshot=current, changes=current.changes_since(selected.identity),
            observations=owner, root=before, directory=tmp_path / 'changed', read_body=read_body) as prepared:
        actual = {index.source_identity(row): row for row in prepared.sources()}
        assert index.source_identity(paper) in prepared.old_source_ids
        assert 'source_committee_code' not in actual[index.source_identity(paper)]
    with closing(WorkingCatalog(tmp_path / 'reference.sqlite')) as work:
        reference = SourceObservationTrace(work).replay(decode_table(store.read(CAPTURES_KEY)), store.read, read_body)
        expected = {index.source_identity(row): row for row in reference.values()}
    assert actual == expected


def test_explicit_retained_body_readings_preserve_capture_facts_without_shared_cache(tmp_path):
    import pyarrow.parquet as pq
    class NoGlobalCache:
        def read(self, key):
            raise AssertionError('Shared processing payload read: ' + key)
        def keys(self, prefix):
            raise AssertionError('Shared processing listing: ' + prefix)
        def put(self, *args, **kwargs):
            raise AssertionError('Shared processing cache write')
    root = tmp_path / 'output'
    (root / 'indexes').mkdir(parents=True)
    with closing(WorkingCatalog(tmp_path / 'filename.sqlite')) as work:
        index.write_filename_metadata(root, [dict(body_key='retained-body', filename='paper.pdf',
            source_url='https://example.gov/paper.pdf')], working=work, workers=1,
            cache_store=NoGlobalCache(), retained_body_readings=[dict(body_key='retained-body',
                parser_fingerprint='original-reader', status='completed', error_type=None,
                body_format=['pdf'], content_document_kind=['testimony'])])
    row, = pq.read_table(root / 'indexes/document-filenames.parquet').to_pylist()
    assert row['body_format'] == ['pdf']
    assert row['content_document_kind'] == ['testimony']


def test_source_update_proof_refuses_dropping_unrelated_observation_routes(tmp_path):
    from congress_api.retention.source_update_proof import retain_source_update, verify_source_update
    from congress_api.retention.source_observations import observation_id
    native, store = MemoryNative(), SelectorStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='route-proof', max_rows=4, max_bytes=4096)
    def stage(path, keys):
        with closing(WorkingCatalog(path)) as work:
            trace = SourceObservationTrace(work)
            for key, event in keys:
                trace(dict(receipt_key=key, receipt_line=1, kind='event', value=event, access='read'))
            return owner.prepare(None, trace)
    root = stage(tmp_path / 'before.sqlite', [('changed', '1'), ('unrelated', '2')])
    dropped = stage(tmp_path / 'invalid.sqlite', [('changed', '3')])
    before = dict(root=root)
    after = dict(root=dropped, namespace='route-proof', max_rows=4, max_bytes=4096)
    base = dict(selector_sha256=None, selected_ref=None)
    reference = retain_source_update(store, base=base, before=before, after=after,
        schema=index.SOURCE_SCHEMA, replacements=[], deletions=[], observations=[observation_id('changed', 1)])
    with pytest.raises(ValueError, match='unrelated observation routing'):
        verify_source_update(store, reference, native=native, base=base, before=before, rows=[], deletions=[])
