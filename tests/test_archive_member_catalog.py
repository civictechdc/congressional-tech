"""Archive members are inventory files, not aliases of their ZIP download URL."""
import asyncio
import json

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from congress_api.retention.raw_catalog import rebuild_catalog
from test_archive_member_capture import URL, zip_bytes, response
from test_async_capture import receipts
from test_raw_catalog import table
from test_raw_source_sync import MemoryStore


def test_member_metadata_and_names_survive_receipt_to_inventory(tmp_path):
    store = MemoryStore()
    data = zip_bytes([('folder/hearing.xml', b'<hearing/>'),
                      ('other/hearing.xml', b'<hearing id="2"/>'),
                      ('folder/hearing.xml', b'<hearing/>')])
    archive = Archive(store, 'zip-inventory')
    result = asyncio.run(run_async(archive, [{'url': URL}], fetch=lambda _: response(data), limit=1))
    assert sum(v for k, v in result['body_metadata'].items() if k != 'reused') == 3
    assert len(archive.captures) == 4
    receipt, = receipts(store)
    members = receipt['record']['archive_members']
    keys = {c['body_key'] for c in receipt['captures'][1:]}
    rebuild_catalog(store, workers=1)
    rows = [r for r in table(store).to_pylist() if r['body_key'] in keys]
    assert len(rows) == 2
    assert all(r['filename'] == 'hearing.xml' and r['source_url'] is None for r in rows)
    assert all(r['filename_origins'] == ['archive_member'] for r in rows)
    pointers = {p for row in rows for p in row['source_capture_pointer']}
    assert {json.dumps(['archive_members', i, 'content', 'body']) for i in range(3)} <= pointers
    assert all(r['source_capture_url'] == [URL] for r in rows)
    assert all(r['media_type'] == ['application/xml'] for r in rows)
    assert any(r['filename'] == 'hearing.zip' and r['source_url'] == URL for r in table(store).to_pylist())


def test_archive_member_absolute_links_enter_async_queue(tmp_path):
    store = MemoryStore()
    data = zip_bytes([('links.xml', b'<root><file href="relative.pdf"/><file href="https://example.gov/next.xml"/></root>')])
    calls = []
    def fetch(url):
        calls.append(url)
        return response(data) if url == URL else response(b'<next/>', url, 'application/xml')
    result = asyncio.run(run_async(Archive(store, 'zip-links'), [{'url': URL}], fetch=fetch, limit=2))
    assert calls == [URL, 'https://example.gov/next.xml']
    assert result['saved'] == 2
    assert len(receipts(store)) == 2


def test_member_rows_cannot_replace_zip_url_state_when_rebuilding():
    from congress_api.retention.raw_archive import CAPTURES_KEY, STATE_KEY, encode_table
    import pyarrow as pa
    store = MemoryStore()
    archive = Archive(store, 'zip-recovery')
    state = archive.record(response(zip_bytes([('first.xml', b'<hearing/>')])), outcome='saved', links=[])
    parent_key = state['body_key']
    archive.save()
    store.objects[CAPTURES_KEY] = encode_table(archive.captures.take(pa.array([1, 0])))
    del store.objects[STATE_KEY]
    rebuilt = Archive(store, 'rebuild-url-state')
    assert rebuilt.state[URL]['body_key'] == parent_key
