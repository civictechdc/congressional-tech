"""Exact native partition streams preserve application schema and selection scope."""
from contextlib import contextmanager
from copy import deepcopy
import os
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.catalog_partitions import CatalogTable
from congress_api.retention.docspec import NativeDatasets


SCHEMA = pa.schema([
    pa.field('source_id', pa.string(), nullable=False, metadata={b'application': b'identity'}),
    ('observations', pa.list_(pa.struct([('url', pa.string()), ('values', pa.list_(pa.string()))]))),
], metadata={b'catalog_id': b'candidate', b'grouping_rules': b'v1'})
ROWS = [dict(source_id='a', observations=None), dict(source_id='b', observations=[]),
        dict(source_id='c', observations=[dict(url='caf\u00e9', values=['same', 'same', ''])])]


def pin(name, rows):
    return dict(id=name, verified=True, dataset=dict(computed={}, related=None,
                groups=dict(source=dict(rows=rows))))


class NativeFixture:
    def __init__(self, schema=SCHEMA):
        self.schema = schema.remove_metadata()
        self.reads = []

    @contextmanager
    def source_batches(self, selected):
        self.reads.append(deepcopy(selected))
        table = pa.Table.from_pylist(ROWS, schema=self.schema)
        with pa.RecordBatchReader.from_batches(self.schema, table.to_batches()) as reader:
            yield reader


def test_selected_partition_only_restores_exact_metadata_and_nested_values():
    native = NativeFixture()
    first, untouched = pin('selected', 3), pin('unrelated', 3)
    table = CatalogTable(SCHEMA, [('first', first), ('untouched', untouched)], native=native)
    first['id'] = 'mutated-by-caller'
    actual = pa.Table.from_batches(list(table.iter_batches(partitions=['first'])))
    assert actual.schema.equals(SCHEMA, check_metadata=True)
    assert actual.to_pylist() == ROWS
    assert [selected['id'] for selected in native.reads] == ['selected']
    assert table.rows == 6


@pytest.mark.parametrize('options', [dict(partitions=['missing']), dict(partitions=['first', 'first']),
                                         dict(columns=['missing']), dict(columns=[]),
                                         dict(columns=['source_id', 'source_id'])])
def test_invalid_scope_refuses_before_native_reads(options):
    native = NativeFixture()
    table = CatalogTable(SCHEMA, [('first', pin('selected', 3))], native=native)
    with pytest.raises(ValueError):
        list(table.iter_batches(**options))
    assert native.reads == []


def test_projection_preserves_requested_field_order_and_metadata():
    table = CatalogTable(SCHEMA, [('first', pin('selected', 3))], native=NativeFixture())
    actual = pa.Table.from_batches(list(table.iter_batches(columns=['observations', 'source_id'])))
    assert actual.column_names == ['observations', 'source_id']
    assert actual.schema.metadata == SCHEMA.metadata
    assert actual.schema.field('source_id').metadata == SCHEMA.field('source_id').metadata


@pytest.mark.parametrize('requested', [None, ['second', 'first']])
def test_partition_reads_follow_selector_order_for_default_and_requested_scope(requested):
    native = NativeFixture()
    table = CatalogTable(SCHEMA, [('first', pin('one', 3)), ('second', pin('two', 3))], native=native)
    list(table.iter_batches(partitions=requested))
    assert [selected['id'] for selected in native.reads] == ['one', 'two']


def test_native_schema_mismatch_refuses_before_rows_escape():
    wrong = pa.schema([('source_id', pa.string()), SCHEMA.field('observations')])
    table = CatalogTable(SCHEMA, [('first', pin('selected', 3))], native=NativeFixture(wrong))
    with pytest.raises(ValueError, match='schema differs'):
        next(table.iter_batches())


@pytest.mark.parametrize('rows', [2, 4])
def test_native_row_count_mismatch_refuses(rows):
    table = CatalogTable(SCHEMA, [('first', pin('selected', rows))], native=NativeFixture())
    with pytest.raises(ValueError, match='row count differs'):
        list(table.iter_batches())


def test_uncompleted_or_computed_pins_are_not_source_partitions():
    incomplete = pin('incomplete', 3)
    incomplete['verified'] = False
    computed = pin('computed', 3)
    computed['dataset']['computed'] = dict(extra={})
    for selected in (incomplete, computed):
        with pytest.raises(ValueError, match='completed source-only'):
            CatalogTable(SCHEMA, [('first', selected)], native=NativeFixture())


def test_actual_native_partition_preserves_original_application_schema(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    native = NativeDatasets(binary, tmp_path / 'native')
    source = tmp_path / 'source.parquet'
    pq.write_table(pa.Table.from_pylist(ROWS, schema=SCHEMA), source)
    release = native.run(dict(dataset='catalog-reader', operation='initial', definition='source-v1',
        sql='SELECT * FROM input', input=str(source), expected_digest=native.hash_input(source)['digest']))
    table = CatalogTable(SCHEMA, [('component', release)], native=native)
    actual = pa.Table.from_batches(list(table.iter_batches()))
    assert actual.schema.equals(SCHEMA, check_metadata=True)
    assert actual.to_pylist() == ROWS
