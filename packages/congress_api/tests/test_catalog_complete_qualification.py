"""A complete qualification preserves selected document values as well as IDs."""
from hashlib import sha256

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import MANIFEST_KEY, read_catalog
from congress_api.retention.catalog_updates import update_native_catalog
from congress_api.retention.immutable_metadata import MetadataObjects, encoded
from congress_api.retention.source_update_proof import retain_source_update
from testing_fakes import Native
from test_native_catalog_selection import seed


def test_complete_qualification_refuses_document_only_value_change(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path / 'store'), Native()
    owner, _ = seed(tmp_path, store, native)
    previous = read_catalog(store, native=native)
    sources = pa.Table.from_batches(list(previous.table(
        'filenames', max_ordered_bytes=1 << 20).iter_batches())).to_pylist()
    reference = retain_source_update(store, base=previous.identity, before=None,
        after=dict(namespace='review-observations', root=None, max_rows=64, max_bytes=1 << 20),
        schema=owner.source_schema, replacements=sources, deletions=[])
    objects = MetadataObjects(store, 'source-updates-v1')
    proof = objects.read(reference)
    proof['purpose'] = 'qualification'
    proof['binding'] = sha256(encoded({k: v for k, v in proof.items() if k != 'binding'})).hexdigest()
    reference = objects.put(proof)

    write = index.write_document_indexes
    def change_documents(destination, rows, schema, **kwargs):
        result = write(destination, rows, schema, **kwargs)
        path = destination.with_name('documents.parquet')
        table = pq.read_table(path)
        changed = table.to_pylist()
        assert changed and all(row['document_kind'] is None for row in changed)
        for row in changed:
            row['document_kind'] = ['review-changed-document-only']
        pq.write_table(pa.Table.from_pylist(changed, schema=table.schema), path)
        return result
    monkeypatch.setattr(index, 'write_document_indexes', change_documents)
    selected = store.read(MANIFEST_KEY)
    with pytest.raises(ValueError, match='qualification changes selected documents values'):
        update_native_catalog(store, native=native, previous=previous, dependencies=owner,
            replacements=sources, candidate='qualification', directory=tmp_path / 'qualify',
            max_chunk_rows=64, max_chunk_bytes=1 << 20, rules=dict(grouping='maintained-v1'),
            source_update=reference, full_update=True)
    assert store.read(MANIFEST_KEY) == selected
    current = read_catalog(store, native=native)
    assert current.identity == previous.identity
    assert pa.Table.from_batches(list(current.table(
        'filenames', max_ordered_bytes=1 << 20).iter_batches())).to_pylist() == sources
    assert all(row['document_kind'] is None for batch in current.table(
        'documents', max_ordered_bytes=1 << 20).iter_batches() for row in batch.to_pylist())
