"""Exact selected reading parts replace global capture metadata discovery."""
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.capture_metadata import MetadataWriter, PREFIX, SCHEMA
from native_memory_helpers import memory_raw_storage
from test_raw_storage import SelectorStore


def part(store, run, body, status='completed'):
    references = []
    with MetadataWriter(store, run, on_part=references.append) as writer:
        writer.append(dict(body_key=body, status=status, parser_fingerprint='retained-reader',
                           body_format=['pdf'], content_citation=['exact earlier reading']))
    return references[0]


def test_selected_body_readings_lookup_is_exact_and_never_lists_history():
    store = SelectorStore()
    first = part(store, 'first', 'body:a')
    unrelated = part(store, 'other', 'body:b', 'failed')
    owner = memory_raw_storage(store)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='reading-adoption',
        reading_parts=[first, unrelated], qualify_readings=True))
    store.keys = lambda *a: pytest.fail('Global reading discovery')
    read = store.read
    reads = []
    def counted(key):
        reads.append(key)
        return read(key)
    store.read = counted
    rows = list(selected.body_readings(['body:a']))
    assert len(rows) == 1 and rows[0]['parser_fingerprint'] == 'retained-reader'
    assert rows[0]['content_citation'] == ['exact earlier reading']
    assert first['key'] in reads and unrelated['key'] not in reads
    assert selected.has_body_reading('body:a') and not selected.has_body_reading('missing')
    assert owner.native.reads == []
    change, = selected.changes_since(owner.empty_identity)
    assert list(selected.changed_reading_parts(change)) == [
        {name: reference[name] for name in ('key', 'bytes', 'sha256', 'rows')} for reference in (first, unrelated)]


def test_unqualified_reading_inventory_refuses_and_part_tampering_does_not_select():
    store = SelectorStore()
    owner = memory_raw_storage(store)
    with pytest.raises(RuntimeError, match='reading.*qualification'):
        list(owner.snapshot().body_readings([]))
    reference = part(store, 'first', 'body:a')
    store.objects[reference['key']] = b'changed'
    with pytest.raises(ValueError, match='reading.*identity'):
        owner.prepare(owner.snapshot(), operation='bad-part', reading_parts=[reference], qualify_readings=True)
    assert owner.snapshot().version is None


def test_existing_negative_reading_survives_new_reader_until_explicit_replacement():
    store = SelectorStore()
    old = part(store, 'old', 'body:a', 'unclassified')
    owner = memory_raw_storage(store)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='seed', reading_parts=[old], qualify_readings=True))
    new = part(store, 'new', 'body:a', 'completed')
    kept = owner.publish(owner.prepare(selected, operation='ordinary', reading_parts=[new]))
    assert list(kept.body_readings(['body:a']))[0]['status'] == 'unclassified'
    changed = owner.publish(owner.prepare(kept, operation='explicit-reading', reading_parts=[new], replace_readings=['body:a']))
    assert list(changed.body_readings(['body:a']))[0]['status'] == 'completed'
    assert list(selected.body_readings(['body:a']))[0]['status'] == 'unclassified'


def test_native_capture_reuses_selected_readings_and_orphan_receipts_keep_exact_part_links(tmp_path):
    from congress_api.acquisition.raw_sync import run_sync
    from congress_api.retention.raw_archive import Archive
    from raw_archive_fixtures import adopt_fixture_archive
    from test_raw_source_sync import response
    import gzip
    import json
    store = SelectorStore()
    owner = memory_raw_storage(store)
    adopt_fixture_archive(store, owner, operation='reviewed-empty')
    keys = store.keys
    store.keys = lambda prefix: pytest.fail('Global reading scan') if prefix == PREFIX else keys(prefix)
    archive = Archive(store, 'parts-before-selection', storage=owner)
    publish = owner.publish
    owner.publish = lambda *args: (_ for _ in ()).throw(RuntimeError('Worker lost before selection'))
    with pytest.raises(RuntimeError, match='Worker lost'):
        run_sync(archive, [{'url': 'https://example.gov/a.pdf'}],
            fetch=lambda url: response(url, b'%PDF-1.7\ninvalid\n%%EOF'), limit=1)
    owner.publish = publish
    receipt_key, = store.keys('receipts/')
    receipt = json.loads(gzip.decompress(store.read(receipt_key)).splitlines()[0])
    assert receipt['reading_parts']
    resumed = Archive(store, 'reconcile-known-receipt', storage=owner)
    resumed.save()
    body = resumed.state['https://example.gov/a.pdf']['body_key']
    reading, = resumed.selected.body_readings([body])
    assert reading['status'] == 'failed'
    before = len(keys(PREFIX))
    result = run_sync(Archive(store, 'next-url-same-body', storage=owner), [{'url': 'https://example.gov/b.pdf'}],
        fetch=lambda url: response(url, b'%PDF-1.7\ninvalid\n%%EOF'), limit=1)
    assert result['body_metadata'] == {'reused': 1}
    assert len(keys(PREFIX)) == before


def test_invalid_reading_reference_refuses_before_io():
    from congress_api.retention.raw_readings import part_rows, PART_BYTES
    store = SelectorStore()
    store.read = lambda *args: pytest.fail('Invalid selected part was read')
    valid = dict(key=PREFIX+'run/000001-'+'a'*64+'.parquet', sha256='a'*64, bytes=10, rows=1)
    for bad in [dict(valid, key='bodies/elsewhere.gz'), dict(valid, bytes=PART_BYTES+1), dict(valid, rows=0)]:
        with pytest.raises(ValueError, match='identity|bounds'):
            list(part_rows(store, bad))


def test_interrupted_explicit_reinspection_keeps_replacement_intent():
    from congress_api.retention.raw_archive import Archive
    from raw_archive_fixtures import adopt_fixture_archive
    from test_raw_source_sync import response
    store = SelectorStore()
    owner = memory_raw_storage(store)
    adopt_fixture_archive(store, owner, operation='seed')
    archive = Archive(store, 'reinspect-before-selection', storage=owner)
    archive.record(response('https://example.gov/a.pdf', b'%PDF-1.7\ninvalid\n%%EOF'), outcome='saved', links=[])
    body = archive.state['https://example.gov/a.pdf']['body_key']
    # Use the real captured body identity in both old and replacement parts.
    old = part(store, 'old-body', body, 'failed')
    owner.publish(owner.prepare(owner.snapshot(), operation='old-body-reading', reading_parts=[old]))
    archive.selected = owner.snapshot()
    new = part(store, 'new-body', body, 'completed')
    archive.register_reading_part(new, replace=[body])
    archive.flush()
    resumed = Archive(store, 'resume-reinspection', storage=owner)
    resumed.save()
    assert list(resumed.selected.body_readings([body]))[0]['status'] == 'completed'
