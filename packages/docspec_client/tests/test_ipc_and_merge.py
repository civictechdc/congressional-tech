"""Unit and integration tests for Arrow IPC streaming, UpdateMergeSpec, and shared schema adapter."""
import base64
import json

import pyarrow as pa
import pytest

from docspec_client import (
    NativeDatasets,
    application_schema,
    blake3_hex,
    build_ipc_run_spec,
    build_ipc_update_spec,
    build_update_merge_spec,
    encode_arrow_ipc_stream,
    native_storage_schema,
    restore_application_schema,
)


def test_blake3_hex_known_vectors():
    # Official BLAKE3 test vectors for empty, short, and multi-chunk inputs.
    assert blake3_hex(b'') == 'af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262'
    assert blake3_hex(b'abc') == '6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85'
    # Multi-chunk (> 2048 bytes) deterministic digest
    payload = bytes(i % 251 for i in range(10000))
    digest = blake3_hex(payload)
    assert len(digest) == 64
    assert blake3_hex(memoryview(payload)) == digest


def test_encode_arrow_ipc_stream_and_schema_adapter():
    app_schema = pa.schema([
        pa.field('id', pa.string(), nullable=False),
        pa.field('count', pa.uint64(), nullable=True),
        pa.field('raw_bytes', pa.binary(), nullable=True),
        pa.field('nested', pa.list_(pa.struct([
            pa.field('offset', pa.uint64()),
            pa.field('blob', pa.binary()),
        ]))),
    ])
    table = pa.Table.from_pylist(
        [
            {
                'id': 'row-1',
                'count': (1 << 63) + 42,
                'raw_bytes': b'\x00\xff\x10',
                'nested': [{'offset': 99, 'blob': b'abc'}],
            }
        ],
        schema=app_schema,
    )

    # Legacy storage mapping converts uint64 -> decimal128(20, 0) and binary -> large_binary
    legacy_schema = native_storage_schema(app_schema, native_types=False)
    assert legacy_schema.field('count').type == pa.decimal128(20, 0)
    assert legacy_schema.field('raw_bytes').type == pa.large_binary()

    # Wave 1D+ native storage mapping preserves uint64 and binary directly
    native_schema = native_storage_schema(app_schema, native_types=True)
    assert native_schema.field('count').type == pa.uint64()
    assert native_schema.field('raw_bytes').type == pa.binary()

    # Both storage representations restore losslessly to app_schema
    legacy_ipc = encode_arrow_ipc_stream(table, native_types=False)
    with pa.ipc.open_stream(pa.py_buffer(legacy_ipc)) as reader:
        legacy_read = reader.read_all()
    restored_from_legacy = restore_application_schema(legacy_read, expected_schema=app_schema)
    assert restored_from_legacy.schema.equals(app_schema)
    assert restored_from_legacy.to_pylist() == table.to_pylist()

    native_ipc = encode_arrow_ipc_stream(table, native_types=True)
    with pa.ipc.open_stream(pa.py_buffer(native_ipc)) as reader:
        native_read = reader.read_all()
    assert native_read.schema.field('count').type == pa.uint64()
    assert native_read.schema.field('raw_bytes').type == pa.binary()
    restored_from_native = restore_application_schema(native_read, expected_schema=app_schema)
    assert restored_from_native.schema.equals(app_schema)
    assert restored_from_native.to_pylist() == table.to_pylist()

    # Unchecked application_schema also restores legacy storage schema
    assert application_schema(legacy_schema).equals(app_schema)


def test_build_update_merge_spec_and_ipc_specs():
    merge = build_update_merge_spec(
        order_by='recorded_at',
        columns={
            'recorded_at': 'max',
            'first_seen_at': 'min',
            'domains': 'set_union',
            'name': 'latest_or_backfill',
        },
    )
    assert merge == {
        'order_by': 'recorded_at',
        'columns': {
            'recorded_at': 'max',
            'first_seen_at': 'min',
            'domains': 'set_union',
            'name': 'latest_or_backfill',
        },
    }
    with pytest.raises(ValueError, match='Invalid UpdateMergeStrategy'):
        build_update_merge_spec(order_by='recorded_at', columns={'name': 'bogus'})

    run_spec = build_ipc_run_spec(
        'news_outlets',
        operation='op-01',
        definition='news-v1',
        relationship={'kind': 'coupled', 'family': 'news', 'generation': 'gen-1'},
    )
    assert run_spec == {
        'dataset': 'news_outlets',
        'operation': 'op-01',
        'definition': 'news-v1',
        'sql': 'SELECT * FROM input',
        'relationship': {'kind': 'coupled', 'family': 'news', 'generation': 'gen-1'},
    }

    upd_spec = build_ipc_update_spec(
        'news_outlets',
        operation='upd-01',
        definition='news-v1',
        base='v-01',
        keys=['id'],
        merge=merge,
    )
    assert upd_spec['dataset'] == 'news_outlets'
    assert upd_spec['base'] == 'v-01'
    assert upd_spec['keys'] == ['id']
    assert upd_spec['merge'] == merge


def test_run_ipc_and_update_ipc_headers_and_payload(tmp_path, monkeypatch):
    client = NativeDatasets(tmp_path / 'docspec', tmp_path / 'ws')
    captured = []

    def fake_request_ipc(path, ipc_bytes, spec, *, blake3_digest=None, dispatch=None):
        if dispatch is not None:
            dispatch['submitted'] = True
        captured.append({
            'path': path,
            'spec': spec,
            'ipc_bytes': ipc_bytes,
            'spec_b64': base64.standard_b64encode(
                json.dumps(spec, separators=(',', ':')).encode('utf-8')
            ).decode('ascii'),
            'blake3': blake3_digest or blake3_hex(ipc_bytes),
        })
        return {
            'dataset': {'dataset': spec['dataset'], 'version': spec['operation'], 'groups': {}},
            'manifest': {'owner': spec['operation'], 'path': 'm.json', 'digest': '0' * 64, 'bytes': 1},
        }

    monkeypatch.setattr(client, '_request_ipc', fake_request_ipc)

    table = pa.Table.from_pylist([{'id': 'o1', 'name': 'Outlet 1', 'recorded_at': '2026-10-18T00:00:00Z'}])
    pin1 = client.run_table(
        table,
        dataset='news_outlets',
        operation='admit-o1',
        definition='news-v1',
        stream_ipc=True,
    )
    assert pin1['dataset']['version'] == 'admit-o1'
    assert captured[0]['path'] == '/run'
    assert captured[0]['spec']['dataset'] == 'news_outlets'
    assert len(captured[0]['blake3']) == 64

    merge = build_update_merge_spec(
        order_by='recorded_at',
        columns={'name': 'latest_or_backfill', 'recorded_at': 'max'},
    )
    pin2 = client.update_table(
        table,
        dataset='news_outlets',
        operation='upsert-o1',
        definition='news-v1',
        base='admit-o1',
        keys=['id'],
        merge=merge,
        stream_ipc=True,
    )
    assert pin2['dataset']['version'] == 'upsert-o1'
    assert captured[1]['path'] == '/updates/run'
    assert captured[1]['spec']['merge'] == merge


@pytest.mark.parametrize('logical,physical,low,high', [
    (pa.int8(), pa.int32(), -(1 << 7), (1 << 7) - 1),
    (pa.int16(), pa.int32(), -(1 << 15), (1 << 15) - 1),
    (pa.uint8(), pa.int32(), 0, (1 << 8) - 1),
    (pa.uint16(), pa.int32(), 0, (1 << 16) - 1),
    (pa.uint32(), pa.int64(), 0, (1 << 32) - 1),
])
def test_producer_parquet_uses_lossless_iceberg_integer_widths(tmp_path, logical, physical, low, high):
    import pyarrow.parquet as pq
    from docspec_client.transport import _write_producer_parquet
    schema = pa.schema([
        pa.field('value', logical, metadata={b'origin': b'application-width'}),
        pa.field('samples', pa.list_(pa.field('reading', logical))),
    ], metadata={b'origin': b'application-schema'})
    table = pa.Table.from_pylist([
        dict(value=low, samples=[low, high, None]),
        dict(value=high, samples=None),
        dict(value=None, samples=[]),
    ], schema=schema)
    path = tmp_path / 'producer.parquet'
    _write_producer_parquet(table, path)
    stored = pq.read_table(path)
    assert stored.schema.field('value').type == physical
    assert stored.schema.field('samples').type.value_type == physical
    assert stored.to_pylist() == table.to_pylist()
    restored = restore_application_schema(stored, expected_schema=schema)
    assert restored.equals(table, check_metadata=True)
    assert table.schema.equals(schema, check_metadata=True)


@pytest.mark.parametrize('container', ['struct', 'list', 'large_list'])
def test_readback_restores_nested_array_metadata_and_list_fields(container):
    native = pa.struct([pa.field('labels', pa.list_(pa.field('element', pa.string(),
        metadata={b'PARQUET:field_id': b'52'})), metadata={b'PARQUET:field_id': b'5'})])
    declared = pa.struct([pa.field('labels', pa.list_(pa.field('application_item', pa.string(),
        metadata={b'origin': b'application-item'})), metadata={b'origin': b'application-field'})])
    values = [{'labels': ['é', None]}, None, {'labels': []}, {'labels': None}]
    if container != 'struct':
        wrap = pa.list_ if container == 'list' else pa.large_list
        native = wrap(pa.field('element', native, metadata={b'PARQUET:field_id': b'3'}))
        declared = wrap(pa.field('observation', declared, metadata={b'origin': b'application-observation'}))
        values = [values, None, [], [None]]
    original = pa.array(values + values, type=native).slice(1, 6)
    physical = pa.Table.from_arrays([pa.chunked_array([original.slice(0, 2), original.slice(2)])], names=['value'])
    schema = pa.schema([pa.field('value', declared, metadata={b'origin': b'application-column'})],
                       metadata={b'origin': b'application-schema'})
    restored = restore_application_schema(physical, expected_schema=schema)
    assert restored.schema.equals(schema, check_metadata=True)
    assert restored.to_pylist() == physical.to_pylist()
    assert restored['value'].type.equals(declared, check_metadata=True)
    assert all(chunk.type.equals(declared, check_metadata=True) for chunk in restored['value'].chunks)
    assert not physical['value'].type.equals(declared, check_metadata=True)
