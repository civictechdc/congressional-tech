"""Registration overlaps bounded proof-page reads; component checks stay serial."""
from collections import Counter
import json
import threading
import time

import pyarrow as pa
import pytest

from congress_api.retention import catalog_batches as catalog
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
    store.reads.clear()
    return store, refs


def test_page_remember_default_is_unchanged_and_optional(fixture, monkeypatch):
    store, refs = fixture
    monkeypatch.delenv('PYTEST_CURRENT_TEST')
    monkeypatch.setattr(catalog, '_PARSED_COMPONENT_PAGES', {})
    reader = catalog.CatalogComponentReader(store)
    ref = refs[0][1]['page']
    page = reader.page(ref, remember=False)
    assert catalog._PARSED_COMPONENT_PAGES == {}
    assert reader.page(ref) == page
    assert ref['sha256'] in catalog._PARSED_COMPONENT_PAGES
