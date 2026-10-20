"""Changed catalog chunks prepare independently without selecting publication."""
from copy import deepcopy
import os
import shutil

import pyarrow as pa
import pytest

from congress_api.retention.catalog_publication import prepare_native_catalog_chunks
from congress_api.retention.catalog_partitions import CatalogTable
from congress_api.retention.docspec import DocSpecFailure
from native_test_helpers import native_test_client


SCHEMA = pa.schema([('source_id', pa.string()), ('aliases', pa.list_(pa.string()))],
                   metadata={b'catalog_id': b'candidate'})


def chunk(orders=(7, 3), aliases=None):
    return pa.Table.from_pylist([
        dict(source_id='a', aliases=[] if aliases is None else aliases, _catalog_order=orders[0]),
        dict(source_id='b', aliases=['same', 'same'], _catalog_order=orders[1]),
    ], schema=SCHEMA.append(pa.field('_catalog_order', pa.int64(), nullable=False)))


class NativeRecorder:
    def __init__(self):
        self.calls = []

    def run_table(self, table, **request):
        self.calls.append((table, request))
        return dict(id='initial', verified=True, dataset=dict(computed={}, related=None,
                    groups=dict(source=dict(rows=len(table)))))


def prepare(native, chunks, **options):
    return prepare_native_catalog_chunks(native, chunks, label='filenames', component='component',
        candidate='exact-base-and-change', schema=SCHEMA, max_chunk_rows=2,
        max_chunk_bytes=4096, **options)


def test_empty_change_prepares_nothing():
    native = NativeRecorder()
    assert prepare(native, []) == []
    assert native.calls == []


def test_chunk_preparation_binds_stable_independent_candidates_and_order_ranges():
    native = NativeRecorder()
    first = prepare(native, [chunk()])
    replay = prepare(native, [chunk()])
    assert first == replay
    assert first[0]['rows'] == 2
    assert (first[0]['order_min'], first[0]['order_max']) == (3, 7)
    assert native.calls[0][1] == native.calls[1][1]
    assert native.calls[0][1]['operation'] == 'initial'
    assert native.calls[0][1]['definition'] == 'catalog-chunk-v1'
    other = prepare_native_catalog_chunks(native, [chunk()], label='filenames', component='component',
        candidate='competing-base-and-change', schema=SCHEMA, max_chunk_rows=2, max_chunk_bytes=4096)
    assert other[0]['name'] != first[0]['name']


@pytest.mark.parametrize('physical,error', [
    (chunk((1, 1)), 'unique'), (chunk((None, 1)), 'nonnull'),
    (chunk().drop(['_catalog_order']), 'order field'),
    (chunk().drop(['aliases']), 'schema differs'),
    (pa.concat_tables([chunk(), chunk((8, 9))]), 'chunk budget'),
])
def test_invalid_changed_chunk_refuses_before_native_effects(physical, error):
    native = NativeRecorder()
    with pytest.raises(ValueError, match=error):
        prepare(native, [physical])
    assert native.calls == []


def test_overlapping_chunk_positions_refuse_instead_of_selecting_mixed_order():
    native = NativeRecorder()
    with pytest.raises(ValueError, match='order ranges'):
        prepare(native, [chunk(), chunk((6, 8))])
    assert len(native.calls) == 1  # The completed first candidate remains native-owned.


def test_actual_native_candidate_replay_and_conflict_preserve_prepared_pin(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    native = native_test_client(binary, tmp_path / 'native')
    first = prepare(native, [chunk()])
    assert prepare(native, [chunk()]) == first
    table = CatalogTable(SCHEMA, [(first[0]['name'], first[0]['release'])], native=native,
                         order_column='_catalog_order', max_ordered_bytes=4096)
    actual = pa.Table.from_batches(list(table.iter_batches()))
    assert actual.schema.equals(SCHEMA, check_metadata=True)
    assert actual.to_pylist() == [dict(source_id='b', aliases=['same', 'same']), dict(source_id='a', aliases=[])]
    before = deepcopy(first)
    with pytest.raises(DocSpecFailure, match='operation_conflict'):
        prepare(native, [chunk(aliases=['correction-under-same-candidate'])])
    assert native.release(first[0]['name'], 'initial') == before[0]['release']
