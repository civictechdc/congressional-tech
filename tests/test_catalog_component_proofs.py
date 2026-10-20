"""Durable changed-component checks bind exact pins, schemas and validator rules."""
from copy import deepcopy
import os
import shutil

import pyarrow as pa
import pytest

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog_component
from congress_api.retention.catalog_batches import prepare_native_catalog_components, iterator_prepared_components
from congress_api.retention.immutable_metadata import MetadataObjects
from congress_api.retention import catalog_validation
from native_test_helpers import native_test_client


SCHEMA = pa.schema([('source_id', pa.string()), ('document_id', pa.string()),
                    ('aliases', pa.list_(pa.string()))], metadata={b'catalog_id': b'candidate'})


def chunk(source, order, *, document='doc'):
    schema = SCHEMA.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    return pa.Table.from_pylist([dict(source_id=source, document_id=document,
                                    aliases=['same', 'same'], _catalog_order=order)], schema=schema)


class NativeRecorder:
    def __init__(self):
        self.calls = []

    def run_table(self, table, **request):
        self.calls.append((table, request))
        return dict(id='initial', verified=True, dataset=dict(dataset=request['dataset'], computed={}, related=None,
                    groups=dict(source=dict(rows=len(table)))))


def prepare(store, native, *, documents=None):
    prepared = prepare_native_catalog_components(store, native, candidate='base-and-change',
        source_chunks=[chunk('a', 3), chunk('b', 7)],
        document_chunks=[chunk('b', 0)] if documents is None else documents,
        source_schema=SCHEMA, document_schema=SCHEMA, max_chunk_rows=1, max_chunk_bytes=4096)
    return next(iterator_prepared_components(store, prepared))[1]


def test_durable_proof_survives_new_owner_without_native_payload_reads(tmp_path):
    store, native = LocalStore(tmp_path), NativeRecorder()
    reference = prepare(store, native)
    assert len(native.calls) == 3
    component = read_catalog_component(LocalStore(tmp_path), reference)
    assert component['validation']['counts'] == dict(source_rows=2, document_rows=1)
    assert component['validation']['source_ids_sha256'] == catalog_validation.catalog_source_ids_digest(['a', 'b'])
    assert component['tables']['filenames']['schema'] == component['tables']['documents']['schema']
    assert len(native.calls) == 3  # Proof read has no native reader or payload access.


def test_reference_failure_never_issues_a_component_proof(tmp_path):
    store, native = LocalStore(tmp_path), NativeRecorder()
    with pytest.raises(ValueError, match='references do not match'):
        prepare(store, native, documents=[chunk('missing', 0)])
    assert len(native.calls) == 3  # Private prepared chunks remain native-owned.
    assert not list((tmp_path / 'indexes/native-manifests/catalog-component-pages-v1').glob('*.json'))


def test_mixed_native_generation_refuses_existing_validation_binding(tmp_path):
    store, native = LocalStore(tmp_path), NativeRecorder()
    reference = prepare(store, native)
    pages = MetadataObjects(store, 'catalog-component-pages-v1')
    physical = MetadataObjects(store, 'catalog-physical-chunks-v1')
    page = pages.read(reference['page'])
    name = page['components']['doc']['tables']['documents']['chunks'][0]['name']
    changed = deepcopy(physical.read(page['chunks'][name]))
    changed['release']['id'] = 'different-native-version'
    page['chunks'][name] = physical.put(changed)
    forged = dict(page=pages.put(page), component='doc')
    with pytest.raises(ValueError, match='validation binding'):
        read_catalog_component(store, forged)


def test_upgrade_preserves_historical_read_but_refuses_new_admission_without_revalidation(tmp_path, monkeypatch):
    store, native = LocalStore(tmp_path), NativeRecorder()
    reference = prepare(store, native)
    historical = read_catalog_component(store, reference)
    monkeypatch.setattr(catalog_validation, 'catalog_reference_requirements', lambda: {'validator': 'changed'})
    assert read_catalog_component(store, reference) == historical
    with pytest.raises(ValueError, match='validator requirements'):
        read_catalog_component(store, reference, requirements=catalog_validation.catalog_reference_requirements())
    assert len(native.calls) == 3


def test_actual_native_component_proof_replays_completed_chunks(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    native = native_test_client(binary, tmp_path / 'native')
    store = LocalStore(tmp_path / 'archive')
    reference = prepare(store, native)
    assert prepare(store, native) == reference
    component = read_catalog_component(LocalStore(store.root), reference)
    assert component['validation']['counts'] == dict(source_rows=2, document_rows=1)
