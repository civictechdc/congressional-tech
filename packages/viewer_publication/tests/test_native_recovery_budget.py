"""Recovery callers admit declared producer bounds while retaining ordering."""

import pyarrow as pa
import pytest
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_partitions import CatalogTable
from congress_api.retention.catalog_rows import CatalogRows
from test_catalog_coalesced_batches import Native
from test_native_preparation import first, fixture_builder
from viewer_publication import native as preparation, publish_viewer_r2 as publisher


def test_projected_recovery_read_preserves_values_order_and_declared_bound(tmp_path):
    source_schema = pa.schema([('source_id', pa.string()), ('document_id', pa.string()),
        ('source_url', pa.string()), ('source_occurrences', pa.list_(pa.struct([('name', pa.string())])))])
    physical = source_schema.append(pa.field('_catalog_order', pa.int64(), nullable=False))
    expected = [dict(source_id='first', document_id='doc', source_url='https://first', source_occurrences=[], _catalog_order=0),
                dict(source_id='last', document_id='doc', source_url='https://last', source_occurrences=[], _catalog_order=1)]
    table = pa.Table.from_pylist(list(reversed(expected)), schema=physical)
    store, native = LocalStore(tmp_path / 'store'), Native()
    pin = CatalogRows(native=native, store=store).write(table, dataset='recovery-budget',
        operation='fixture', definition='fixture', max_rows=64, max_bytes=96 << 20)
    assert pin['catalog_rows']['max_bytes'] == 96 << 20
    def selected(limit):
        return CatalogTable(source_schema, [('chunk', pin)], native=native, store=store,
            order_column='_catalog_order', max_ordered_bytes=limit,
            views={'chunk': dict(components=['doc'], rows=2)})
    with pytest.raises(ValueError, match='Ordered catalog partition exceeds Arrow byte bound'):
        list(selected(64 << 20).iter_batches(columns=['source_url']))
    actual = pa.Table.from_batches(list(selected(96 << 20).iter_batches(columns=['source_url'])))
    assert actual['source_url'].to_pylist() == [row['source_url'] for row in expected]
    assert actual.schema.equals(pa.schema([source_schema.field('source_url')]))
    # Order proofs still reject duplicate physical positions at the raised cap.
    core_name = pin['dataset']['dataset']
    core = native.tables[core_name]
    native.tables[core_name] = core.set_column(core.schema.get_field_index('_catalog_order'),
        core.schema.field('_catalog_order'), pa.array([0, 0], type=pa.int64()))
    with pytest.raises(ValueError, match='order values must be nonnull and unique'):
        list(selected(96 << 20).iter_batches(columns=['source_url']))


def test_native_preparation_uses_the_qualified_recovery_caller_cap(tmp_path, monkeypatch):
    import viewer_publication.filename_native_recoveries as recoveries
    snapshot, native, remote, manifest, expected, previous = first(tmp_path)
    original = recoveries.index_catalog_recoveries
    seen = []
    def checked(*args, **options):
        assert options['max_ordered_bytes'] == 96 << 20
        seen.append(options['max_ordered_bytes'])
        return original(*args, **options)
    monkeypatch.setattr(recoveries, 'index_catalog_recoveries', checked)
    _, actual = preparation.prepare_native_output(publisher, fixture_builder, remote, snapshot, tmp_path / 'next',
        accepted_record=(None,) * 4, viewer_record=previous)
    assert seen == [96 << 20] and actual == expected
