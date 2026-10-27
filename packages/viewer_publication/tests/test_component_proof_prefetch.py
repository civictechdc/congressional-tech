"""Registration overlaps bounded proof-page reads; component checks stay serial."""
from collections import Counter
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pyarrow as pa
import pytest

from congress_api.retention import catalog_batches as catalog
from congress_api.retention.immutable_metadata import encoded
from viewer_publication import filename_native as native
from test_catalog_coalesced_batches import Store as BaseStore, Native, SCHEMA


class Store(BaseStore):
    def __init__(self, root):
        super().__init__(root)
        self.active = self.peak = 0
        self.lock = threading.Lock()
        self.bad = self.fail = None

    def read(self, key):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(.001)
            if key == self.fail:
                raise OSError('proof unavailable')
            if key == self.bad:
                self.reads.append(key)
                return b'corrupt'
            return super().read(key)
        finally:
            with self.lock:
                self.active -= 1


@pytest.fixture
def fixture(tmp_path):
    store = Store(tmp_path / 'store')
    physical = SCHEMA.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    table = pa.Table.from_pylist([dict(source_id=f'source-{i}', document_id=f'doc-{i:04}',
        aliases=['same', 'same'], _catalog_order=i) for i in range(450)], schema=physical)
    chunks = [table.slice(i, 256) for i in range(0, len(table), 256)]
    prepared = catalog.prepare_native_catalog_components(store, Native(), candidate='proof-prefetch',
        source_chunks=chunks, document_chunks=chunks, source_schema=SCHEMA, document_schema=SCHEMA,
        max_chunk_rows=256, max_chunk_bytes=1 << 20)
    refs = list(catalog.iterator_prepared_components(store, prepared))
    def owner():
        db = sqlite3.connect(':memory:')
        current = native.NativeComponents(SimpleNamespace(store=store), None, None, db,
            viewer=SimpleNamespace(), policy=SimpleNamespace(), metrics={})
        for component, ref in refs:
            db.execute('INSERT INTO components(id,reference,page) VALUES (?,?,?)',
                (component, encoded(ref).decode(), encoded(ref['page']).decode()))
        db.commit()
        return current
    store.reads.clear()
    return store, refs, owner


def rows(current):
    return {table: current.db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
            for table in ['components', 'stats', 'chunks', 'views']}


def writes(current):
    result = []
    current.db.set_trace_callback(lambda sql: result.append(sql) if sql.startswith(('INSERT', 'UPDATE')) else None)
    return result


@pytest.mark.parametrize('issued', [False, True])
def test_registration_keeps_checks_order_and_one_get_per_proof_page(fixture, monkeypatch, issued):
    store, refs, owner = fixture
    serial = owner()
    before_writes = writes(serial)
    reader = catalog.CatalogComponentReader(store)
    for component, raw in serial.db.execute('SELECT id,reference FROM components ORDER BY page,id'):
        serial._register_component(component, raw, reader)
    expected = rows(serial)
    expected_reads = Counter(store.reads)
    store.reads.clear()
    store.peak = 0
    monkeypatch.delenv('PYTEST_CURRENT_TEST')
    monkeypatch.setattr(catalog, '_PARSED_COMPONENT_PAGES', {})
    proof_keys = {ref['page']['key'] for _, ref in refs}
    issued_pages = {ref['page']['sha256'] for _, ref in refs} if issued else set()
    monkeypatch.setattr(catalog, '_VERIFIED_COMPONENT_PAGES', issued_pages)
    original = catalog._require_component
    checked = []
    def require(value, **kwargs):
        checked.append(value['component'])
        return original(value, **kwargs)
    monkeypatch.setattr(catalog, '_require_component', require)
    candidate = owner()
    after_writes = writes(candidate)
    candidate._register_chunks()
    assert rows(candidate) == expected
    assert after_writes == before_writes
    assert Counter(store.reads) == expected_reads
    proof_keys = {ref['page']['key'] for _, ref in refs}
    assert len(proof_keys) > native.COMPONENT_SCOPE_WORKERS
    assert all(Counter(store.reads)[key] == 1 for key in proof_keys)
    assert len(refs) == 450
    assert len(checked) == (0 if issued else len(refs))
    assert catalog._PARSED_COMPONENT_PAGES == {}
    assert 1 < store.peak <= native.COMPONENT_SCOPE_WORKERS
    assert store.active == 0


@pytest.mark.parametrize('damage', ['digest', 'fetch', 'binding', 'member_bound', 'component_validation'])
def test_bad_proof_registration_refuses_without_accepted_mutations(fixture, damage):
    store, refs, owner = fixture
    current = owner()
    component, ref = refs[0]
    key = ref['page']['key']
    if damage == 'digest':
        store.bad = key
    elif damage == 'fetch':
        store.fail = key
    elif damage == 'binding':
        # Last proof page has fewer than64 members, so the identity check is reached.
        current.db.execute('UPDATE components SET page=? WHERE id=?',
            (encoded(refs[-1][1]['page']).decode(), component))
    elif damage == 'member_bound':
        altered = dict(component='extra', page=ref['page'])
        current.db.execute('INSERT INTO components(id,reference,page) VALUES (?,?,?)',
            ('extra', encoded(altered).decode(), encoded(ref['page']).decode()))
    else:
        value = json.loads(store.read(key))
        value['components'][component]['validation']['counts']['document_rows'] = 2
        changed = catalog.CatalogComponentReader(store).pages.put(value)
        altered = dict(ref, page=changed)
        current.db.execute('UPDATE components SET reference=?,page=? WHERE id=?',
            (encoded(altered).decode(), encoded(changed).decode(), component))
    current.db.commit()
    before = rows(current)
    with pytest.raises((ValueError, OSError)):
        with current.db:
            current._register_chunks()
    assert rows(current) == before
    assert store.active == 0
    assert store.peak <= native.COMPONENT_SCOPE_WORKERS


def test_page_remember_default_is_unchanged_and_optional(fixture, monkeypatch):
    store, refs, _ = fixture
    monkeypatch.delenv('PYTEST_CURRENT_TEST')
    monkeypatch.setattr(catalog, '_PARSED_COMPONENT_PAGES', {})
    reader = catalog.CatalogComponentReader(store)
    ref = refs[0][1]['page']
    page = reader.page(ref, remember=False)
    assert catalog._PARSED_COMPONENT_PAGES == {}
    assert reader.page(ref) == page
    assert ref['sha256'] in catalog._PARSED_COMPONENT_PAGES
