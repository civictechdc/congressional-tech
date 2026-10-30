"""Unit tests for the DocSpec ExportPolicy / ExportSpec / ExportPin client surface."""
from docspec_client import (
    NativeDatasets,
    build_export_policy,
    build_export_spec,
    parse_export_pin,
)


def test_build_export_policy_full_surface():
    policy = build_export_policy(
        group='source',
        groups=('source',),
        columns=['source_key', 'document_id', 'collection', 'filename_field_count'],
        filter={'op': 'is_not_null', 'column': 'source_key'},
        computed_columns={
            'filename_field_count': {
                'fn': 'count_non_null',
                'columns': ['raw_leaf', 'normalized_leaf', 'header_leaf'],
            }
        },
        order_by=[
            {'column': 'source_key', 'direction': 'asc', 'nulls_first': False},
        ],
        page_index_columns=['source_key', 'document_id', 'collection'],
        browse_range_columns=['source_key', 'collection'],
        row_group_rows=2048,
    )
    assert set(policy.keys()) <= {
        'group',
        'groups',
        'rows',
        'columns',
        'filter',
        'computed_columns',
        'order_by',
        'page_index_columns',
        'browse_range_columns',
        'row_group_rows',
    }
    assert policy['group'] == 'source'
    assert policy['groups'] == ['source']
    assert policy['rows'] == 'all'
    assert policy['filter'] == {
        'kind': 'is_not_null',
        'expr': {'kind': 'column', 'name': 'source_key'},
    }
    assert isinstance(policy['computed_columns'], dict)
    assert 'filename_field_count' in policy['computed_columns']
    assert policy['order_by'] == [
        {'column': 'source_key', 'direction': 'asc', 'nulls_first': False}
    ]
    assert policy['page_index_columns'] == ['source_key', 'document_id', 'collection']
    assert policy['browse_range_columns'] == ['source_key', 'collection']
    assert policy['row_group_rows'] == 2048


def test_build_export_spec_accepts_pin_or_version_string():
    pin = {
        'id': 'v-sources-01',
        'dataset': 'filename-sources',
        'manifest': {
            'owner': 'v-sources-01',
            'path': 'versions/v-sources-01/manifest.json',
            'digest': 'a' * 64,
            'bytes': 512,
        },
    }
    spec = build_export_spec(
        'filename-sources',
        operation='exp-sources-01',
        source=pin,
        channel='viewer',
        columns=['source_key'],
        groups=('source',),
        order_by=[{'column': 'source_key'}],
        row_group_rows=2048,
    )
    assert set(spec.keys()) == {'dataset', 'operation', 'source', 'channel', 'expected', 'policy'}
    assert spec == {
        'dataset': 'filename-sources',
        'operation': 'exp-sources-01',
        'source': {
            'dataset': 'filename-sources',
            'version': 'v-sources-01',
            'manifest': {
                'owner': 'v-sources-01',
                'path': 'versions/v-sources-01/manifest.json',
                'digest': 'a' * 64,
                'bytes': 512,
            },
        },
        'channel': 'viewer',
        'expected': None,
        'policy': {
            'group': 'source',
            'groups': ['source'],
            'rows': 'all',
            'columns': ['source_key'],
            'order_by': [{'column': 'source_key', 'direction': 'asc', 'nulls_first': False}],
            'row_group_rows': 2048,
        },
    }


def test_parse_export_pin():
    raw_pin = {
        'format': 1,
        'id': 'exp-01',
        'dataset': 'filename-sources',
        'source': {
            'dataset': 'filename-sources',
            'version': 'v-01',
            'manifest': {
                'owner': 'v-01',
                'path': 'versions/v-01/manifest.json',
                'digest': 'a' * 64,
                'bytes': 100,
            },
        },
        'source_revision': 1,
        'policy': {
            'group': 'source',
            'rows': 'all',
            'columns': ['source_key', 'collection'],
        },
        'object': {
            'owner': 'exp-01',
            'path': 'exports/exp-01/source.parquet',
            'digest': 'c' * 64,
            'bytes': 4096,
        },
        'rows': 10,
        'fields': [
            {'id': 1, 'name': 'source_key', 'data_type': 'Utf8', 'nullable': False},
            {'id': 2, 'name': 'collection', 'data_type': 'Utf8', 'nullable': True},
        ],
        'validation': {
            'object': {
                'owner': 'exp-01',
                'path': 'exports/exp-01/source.parquet',
                'digest': 'c' * 64,
                'bytes': 4096,
            },
            'rows': 10,
            'sampled_rows': 10,
            'sampled_decoded_bytes': 512,
        },
        'browse_ranges': [
            {
                'row_group': 0,
                'start_row': 0,
                'num_rows': 10,
                'min_values': {'source_key': 'doc-001'},
                'max_values': {'source_key': 'doc-010'},
            }
        ],
    }
    parsed = parse_export_pin(raw_pin)
    assert parsed['rows'] == 10
    assert parsed['object']['bytes'] == 4096


def test_export_table_dispatches_normalized_request(tmp_path, monkeypatch):
    client = NativeDatasets(tmp_path / 'docspec', tmp_path / 'ws')
    captured = {}

    def fake_request(path, request, *, dispatch=None):
        captured['path'] = path
        captured['request'] = request
        return {
            'format': 1,
            'id': request['operation'],
            'dataset': request['dataset'],
            'source': request['source'],
            'source_revision': 1,
            'policy': request['policy'],
            'object': {
                'owner': request['operation'],
                'path': 'exports/s.parquet',
                'digest': '2' * 64,
                'bytes': 128,
            },
            'rows': 3,
            'fields': [],
            'validation': {
                'object': {
                    'owner': request['operation'],
                    'path': 'exports/s.parquet',
                    'digest': '2' * 64,
                    'bytes': 128,
                },
                'rows': 3,
                'sampled_rows': 3,
                'sampled_decoded_bytes': 64,
            },
        }

    monkeypatch.setattr(client, '_request', fake_request)
    pin = client.export_table(
        'filename-components',
        operation='exp-comp-01',
        source={
            'dataset': 'filename-components',
            'version': 'v-comp-01',
            'manifest': {
                'owner': 'v-comp-01',
                'path': 'versions/v-comp-01/manifest.json',
                'digest': '0' * 64,
                'bytes': 1,
            },
        },
        channel='viewer',
        columns=['filename', 'document_id'],
        groups=('source',),
        order_by=[{'column': 'filename'}, {'column': 'document_id'}],
    )
    assert captured['path'] == '/exports/run'
    assert set(captured['request'].keys()) == {'dataset', 'operation', 'source', 'channel', 'expected', 'policy'}
    assert captured['request']['dataset'] == 'filename-components'
    assert captured['request']['policy']['order_by'] == [
        {'column': 'filename', 'direction': 'asc', 'nulls_first': False},
        {'column': 'document_id', 'direction': 'asc', 'nulls_first': False},
    ]
    assert pin['rows'] == 3
    assert pin['object']['bytes'] == 128
