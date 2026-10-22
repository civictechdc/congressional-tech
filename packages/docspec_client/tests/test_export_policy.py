"""Unit tests for the DocSpec ExportPolicy / ExportSpec / ExportPin client surface."""
from pathlib import Path
import pytest

from docspec_client import (
    NativeDatasets,
    build_export_policy,
    build_export_spec,
    facet_summary,
    parse_export_pin,
)


def test_build_export_policy_full_surface():
    policy = build_export_policy(
        groups=('source',),
        filter={'op': 'is_not_null', 'column': 'source_key'},
        computed_columns=[
            {
                'name': 'filename_field_count',
                'expression': {
                    'fn': 'count_non_null',
                    'columns': ['raw_leaf', 'normalized_leaf', 'header_leaf'],
                },
            }
        ],
        fold_readings=[
            {
                'name': 'filename_readings',
                'fields': ['raw_leaf', 'normalized_leaf', 'header_leaf'],
            }
        ],
        order_by=[
            {'column': 'source_key', 'descending': False, 'nulls_first': False},
        ],
        page_index_columns=['source_key', 'document_id', 'collection'],
        facet_sets=[
            {
                'name': 'sources_facets',
                'columns': ['collection', 'source_role', 'recovery_status'],
            }
        ],
        browse_range_columns=['source_key', 'collection'],
        child_tables=[
            {
                'name': 'occurrences',
                'group': 'occurrences',
                'destination': '/tmp/export/occurrences.parquet',
                'columns': ['owner_id', 'occurrence_order', 'source_id', 'block', 'page'],
                'order_by': [
                    {'column': 'owner_id'},
                    {'column': 'occurrence_order'},
                ],
                'browse_range_columns': ['owner_id'],
                'row_group_rows': 2048,
            }
        ],
        row_group_rows=2048,
    )
    assert policy['groups'] == ['source']
    assert policy['filter'] == {'op': 'is_not_null', 'column': 'source_key'}
    assert policy['computed_columns'][0]['name'] == 'filename_field_count'
    assert policy['fold_readings'] == [
        {
            'name': 'filename_readings',
            'fields': ['raw_leaf', 'normalized_leaf', 'header_leaf'],
        }
    ]
    assert policy['order_by'] == [
        {'column': 'source_key', 'descending': False, 'nulls_first': False}
    ]
    assert policy['page_index_columns'] == ['source_key', 'document_id', 'collection']
    assert policy['facet_sets'] == [
        {
            'name': 'sources_facets',
            'columns': ['collection', 'source_role', 'recovery_status'],
        }
    ]
    assert policy['browse_range_columns'] == ['source_key', 'collection']
    assert policy['child_tables'][0]['name'] == 'occurrences'
    assert policy['child_tables'][0]['row_group_rows'] == 2048
    assert policy['child_tables'][0]['order_by'] == [
        {'column': 'owner_id', 'descending': False, 'nulls_first': False},
        {'column': 'occurrence_order', 'descending': False, 'nulls_first': False},
    ]
    assert policy['row_group_rows'] == 2048


def test_build_export_spec_accepts_pin_or_version_string(tmp_path):
    pin = {
        'id': 'v-sources-01',
        'dataset': {'dataset': 'filename-sources', 'version': 'v-sources-01'},
    }
    spec = build_export_spec(
        'filename-sources',
        operation='exp-sources-01',
        version=pin,
        channel='viewer',
        destination=tmp_path / 'sources',
        groups=('source',),
        order_by=[{'column': 'source_key'}],
        row_group_rows=2048,
    )
    assert spec == {
        'dataset': 'filename-sources',
        'operation': 'exp-sources-01',
        'version': 'v-sources-01',
        'channel': 'viewer',
        'destination': str(tmp_path / 'sources'),
        'policy': {
            'groups': ['source'],
            'order_by': [{'column': 'source_key', 'descending': False, 'nulls_first': False}],
            'row_group_rows': 2048,
        },
    }


def test_parse_export_pin_and_facet_summary():
    raw_pin = {
        'id': 'exp-01',
        'operation': 'exp-01',
        'channel': 'viewer',
        'dataset': {'dataset': 'filename-sources', 'version': 'v-01'},
        'manifest': {'path': '/tmp/m.json', 'digest': 'a' * 64, 'size': 100},
        'policy_digest': 'b' * 64,
        'destination': '/tmp/out',
        'files': [
            {'group': 'source', 'path': '/tmp/out/source.parquet', 'digest': 'c' * 64, 'bytes': 4096, 'rows': 10},
        ],
        'facets': [
            {'facet_set': 'sources_facets', 'column': 'collection', 'value': 'house', 'count': 6},
            {'facet_set': 'sources_facets', 'column': 'collection', 'value': 'senate', 'count': 3},
            {'facet_set': 'sources_facets', 'column': 'collection', 'value': None, 'count': 1},
        ],
        'browse_ranges': [
            {
                'group': 'source',
                'path': '/tmp/out/source.parquet',
                'row_group': 0,
                'row_offset': 0,
                'rows': 10,
                'column': 'source_key',
                'min': 'doc-001',
                'max': 'doc-010',
                'null_count': 0,
            }
        ],
        'child_tables': {
            'occurrences': {
                'name': 'occurrences',
                'group': 'occurrences',
                'file': {
                    'group': 'occurrences',
                    'path': '/tmp/out/occurrences.parquet',
                    'digest': 'd' * 64,
                    'bytes': 8192,
                    'rows': 42,
                },
                'total_rows': 42,
                'total_bytes': 8192,
                'browse_ranges': [],
            }
        },
    }
    parsed = parse_export_pin(raw_pin)
    assert parsed['total_rows'] == 10
    assert parsed['total_bytes'] == 4096
    assert parsed['child_tables']['occurrences']['total_rows'] == 42

    summary = facet_summary(parsed, facet_set='sources_facets', column='collection')
    assert summary == {
        'values': {'house': 6, 'senate': 3},
        'null_count': 1,
    }


def test_export_table_dispatches_normalized_request(tmp_path, monkeypatch):
    client = NativeDatasets(tmp_path / 'docspec', tmp_path / 'ws')
    captured = {}

    def fake_request(path, request, *, dispatch=None):
        captured['path'] = path
        captured['request'] = request
        return {
            'id': request['operation'],
            'operation': request['operation'],
            'channel': request['channel'],
            'dataset': {'dataset': request['dataset'], 'version': request['version']},
            'manifest': {'path': '/tmp/m', 'digest': '0' * 64, 'size': 1},
            'policy_digest': '1' * 64,
            'destination': request['destination'],
            'files': [{'group': 'source', 'path': '/tmp/s.parquet', 'digest': '2' * 64, 'bytes': 128, 'rows': 3}],
        }

    monkeypatch.setattr(client, '_request', fake_request)
    pin = client.export_table(
        'filename-components',
        operation='exp-comp-01',
        version='v-comp-01',
        channel='viewer',
        destination=tmp_path / 'out',
        groups=('source',),
        order_by=[{'column': 'filename'}, {'column': 'document_id'}],
    )
    assert captured['path'] == '/exports/run'
    assert captured['request']['dataset'] == 'filename-components'
    assert captured['request']['policy']['order_by'] == [
        {'column': 'filename', 'descending': False, 'nulls_first': False},
        {'column': 'document_id', 'descending': False, 'nulls_first': False},
    ]
    assert pin['total_rows'] == 3
    assert pin['total_bytes'] == 128
