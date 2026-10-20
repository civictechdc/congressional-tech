"""Retain unsigned values through Iceberg's exact decimal representation."""
import os
import shutil

import pyarrow as pa
import pytest

from native_test_helpers import native_test_client
from congress_api.retention.docspec import NativeDatasets


def test_native_unsigned_roundtrip_keeps_nested_values_and_logical_schema(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    schema = pa.schema([
        pa.field('row', pa.int64(), nullable=False),
        pa.field('unsigned', pa.uint64(), metadata={b'unit': b'exact'}),
        pa.field('extra', pa.struct([
            pa.field('large', pa.uint64()),
            pa.field('nested', pa.list_(pa.binary())),
            pa.field('values', pa.list_(pa.uint64())),
        ])),
    ], metadata={b'application': b'preserved'})
    rows = [
        dict(row=0, unsigned=2**64-1,
             extra=dict(large=2**63, nested=[None, b'exact'], values=[0, None, 2**64-1])),
        dict(row=1, unsigned=0, extra=None),
        dict(row=2, unsigned=None, extra=dict(large=None, nested=[], values=[])),
    ]
    original = pa.Table.from_pylist(rows, schema=schema)
    native = native_test_client(binary, tmp_path / 'native')
    pin = native.run_table(original, dataset='unsigned', operation='initial', definition='typed-test-v1')
    assert native.run_table(original, dataset='unsigned', operation='initial', definition='typed-test-v1') == pin
    fresh = NativeDatasets(binary, native.workspace, limits=native.limits)
    with fresh.source_batches(pin, schema=schema) as reader:
        result = reader.read_all().sort_by([('row', 'ascending')])
    assert result.equals(original, check_metadata=True)
    with fresh.source_batches(pin) as reader:
        assert reader.schema.field('unsigned').type == pa.decimal128(20, 0)
    wrong = schema.set(1, pa.field('unsigned', pa.string()))
    with pytest.raises(ValueError, match='storage schema'):
        with fresh.source_batches(pin, schema=wrong) as reader:
            reader.read_all()


@pytest.mark.parametrize('value', [-1, 2**64])
def test_schema_bound_read_refuses_out_of_range_unsigned_values(tmp_path, monkeypatch, value):
    from decimal import Decimal
    native = NativeDatasets('unused', tmp_path)
    schema = pa.schema([('unsigned', pa.uint64())])
    physical = pa.Table.from_pylist([dict(unsigned=Decimal(value))],
                                   schema=pa.schema([('unsigned', pa.decimal128(20, 0))]))

    def write_native_result(command, release, output, *options):
        with output.open('wb') as target:
            with pa.ipc.new_stream(target, physical.schema) as writer:
                writer.write_table(physical)

    monkeypatch.setattr(native, '_call', write_native_result)
    with pytest.raises(pa.ArrowInvalid):
        with native.source_batches({}, schema=schema) as reader:
            reader.read_all()
