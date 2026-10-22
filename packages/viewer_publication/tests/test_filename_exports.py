"""Tests for ExportPolicy/ExportPin viewer assets, flat occurrences.parquet, and conditional PUT pointer."""
import hashlib
from pathlib import Path

from botocore.exceptions import ClientError
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client import facet_summary, parse_export_pin
from viewer_publication import ConditionalManifestPublisher, publish_manifest_pointer
from viewer_publication.filename_exports import (
    OCCURRENCE_ROW_GROUP_ROWS,
    build_component_export_policy,
    build_component_export_spec,
    build_source_export_policy,
    build_source_export_spec,
    export_viewer_pins,
    fold_source_readings_table,
    publish_occurrence_parquet,
)


def _sample_tables(outlier_occurrences=0):
    occ_struct = pa.struct(
        [
            ('source_page_url', pa.list_(pa.string())),
            ('source_page_title', pa.list_(pa.string())),
            ('source_link_label', pa.list_(pa.string())),
            ('source_occurrence_scope', pa.list_(pa.string())),
        ]
    )
    source_schema = pa.schema(
        [
            ('source_id', pa.string()),
            ('document_id', pa.string()),
            ('filename', pa.string()),
            ('source_url', pa.string()),
            ('body_key', pa.string()),
            ('record_role', pa.list_(pa.string())),
            ('document_kind', pa.list_(pa.string())),
            ('document_family', pa.list_(pa.string())),
            ('format', pa.list_(pa.string())),
            ('congress', pa.list_(pa.string())),
            ('http_status', pa.list_(pa.string())),
            ('response_usable', pa.list_(pa.string())),
            ('response_body_complete', pa.list_(pa.string())),
            ('state_checked_at', pa.list_(pa.string())),
            ('raw_leaf', pa.list_(pa.string())),
            ('normalized_leaf', pa.list_(pa.string())),
            ('header_leaf', pa.list_(pa.string())),
            ('source_occurrences', pa.list_(occ_struct)),
        ]
    )

    occ_a = [
        {
            'source_page_url': ['https://committee.test/hearing'],
            'source_page_title': ['Hearing page'],
            'source_link_label': ['Witness A'],
            'source_occurrence_scope': ['anchor'],
        },
        None,
        {
            'source_page_url': [],
            'source_page_title': ['Second page'],
            'source_link_label': ['José 🏛️'],
            'source_occurrence_scope': None,
        },
    ]
    if outlier_occurrences > 0:
        occ_a = [
            {
                'source_page_url': [f'https://committee.test/p/{i % 50}'],
                'source_page_title': [f'Hearing page {i}'],
                'source_link_label': [f'Label {i}'],
                'source_occurrence_scope': ['anchor'],
            }
            if i % 7 != 0
            else None
            for i in range(outlier_occurrences)
        ]

    s0 = hashlib.sha256(b'source-0').hexdigest()
    s1 = hashlib.sha256(b'source-1').hexdigest()
    s2 = hashlib.sha256(b'source-2').hexdigest()

    sources = pa.Table.from_pylist(
        [
            {
                'source_id': s2,
                'document_id': 'doc-b',
                'filename': 'zeta.pdf',
                'source_url': 'https://committee.test/zeta.pdf',
                'body_key': None,
                'record_role': ['document'],
                'document_kind': ['witness-statement'],
                'document_family': ['statement'],
                'format': ['PDF'],
                'congress': ['118'],
                'http_status': ['200'],
                'response_usable': ['true'],
                'response_body_complete': ['true', 'false'],
                'state_checked_at': ['2026-10-14T09:00:00-04:00'],
                'raw_leaf': ['zeta.pdf'],
                'normalized_leaf': ['zeta.pdf', 'zeta_clean.pdf'],
                'header_leaf': None,
                'source_occurrences': occ_a,
            },
            {
                'source_id': s0,
                'document_id': 'doc-a',
                'filename': 'alpha.pdf',
                'source_url': 'https://committee.test/alpha.pdf',
                'body_key': 'bodies/sha256/ab/' + ('ab' * 32) + '.gz',
                'record_role': ['document'],
                'document_kind': ['transcript'],
                'document_family': ['hearing'],
                'format': ['pdf'],
                'congress': ['117'],
                'http_status': ['200'],
                'response_usable': ['true'],
                'response_body_complete': ['true'],
                'state_checked_at': ['2026-10-14T09:00:00-04:00'],
                'raw_leaf': ['alpha.pdf'],
                'normalized_leaf': None,
                'header_leaf': ['alpha_header.pdf'],
                'source_occurrences': [],
            },
            {
                'source_id': s1,
                'document_id': 'doc-c',
                'filename': None,
                'source_url': 'https://committee.test/none',
                'body_key': None,
                'record_role': ['source-record'],
                'document_kind': None,
                'document_family': None,
                'format': None,
                'congress': None,
                'http_status': None,
                'response_usable': None,
                'response_body_complete': None,
                'state_checked_at': None,
                'raw_leaf': None,
                'normalized_leaf': None,
                'header_leaf': None,
                'source_occurrences': None,
            },
        ],
        schema=source_schema,
    )
    components = sources
    return sources, components


def test_export_policies_and_specs_match_docspec_contract(tmp_path):
    source_spec = build_source_export_spec(
        'filename-sources',
        operation='exp-s-1',
        version='v-1',
        destination=tmp_path / 'sources',
    )
    comp_spec = build_component_export_spec(
        'filename-components',
        operation='exp-c-1',
        version='v-1',
        destination=tmp_path / 'components',
    )
    assert source_spec['policy']['fold_readings'][0]['name'] == 'filename_readings'
    assert source_spec['policy']['computed_columns'][0]['name'] == 'filename_field_count'
    assert source_spec['policy']['child_tables'][0]['name'] == 'occurrences'
    assert source_spec['policy']['child_tables'][0]['row_group_rows'] == OCCURRENCE_ROW_GROUP_ROWS
    assert comp_spec['policy']['order_by'] == [
        {'column': 'filename', 'descending': False, 'nulls_first': False},
        {'column': 'document_id', 'descending': False, 'nulls_first': False},
    ]


def test_export_viewer_pins_sorts_folds_readings_and_writes_flat_occurrences(tmp_path):
    sources, components = _sample_tables(outlier_occurrences=4500)
    exported = export_viewer_pins(sources, components, tmp_path / 'export')

    sources_pin = parse_export_pin(exported['sources'])
    components_pin = parse_export_pin(exported['components'])

    assert sources_pin['total_rows'] == 3
    assert components_pin['total_rows'] == 3

    # Verify components.parquet is sorted by (filename ASC NULLS LAST, document_id ASC)
    comp_table = pq.read_table(tmp_path / 'export' / 'components.parquet')
    assert comp_table['filename'].to_pylist() == ['alpha.pdf', 'zeta.pdf', None]
    assert comp_table['document_id'].to_pylist() == ['doc-a', 'doc-b', 'doc-c']

    # Verify sources.parquet has folded filename_readings and filename_field_count
    src_table = pq.read_table(tmp_path / 'export' / 'sources.parquet')
    src_rows = {row['document_id']: row for row in src_table.to_pylist()}
    assert src_rows['doc-b']['filename_field_count'] == 2
    assert src_rows['doc-b']['filename_readings'] == [
        {'field': 'raw_leaf', 'values': ['zeta.pdf']},
        {'field': 'normalized_leaf', 'values': ['zeta.pdf', 'zeta_clean.pdf']},
    ]
    assert src_rows['doc-b']['fact_alternatives'] == [
        {'field': 'response_body_complete', 'values': ['true', 'false']},
    ]

    # Verify flat occurrences.parquet has 2048-row groups and browse_ranges
    occ_child = sources_pin['child_tables']['occurrences']
    assert occ_child['total_rows'] == 4500
    assert len(occ_child['browse_ranges']) == 3  # ceil(4500 / 2048) = 3 row groups
    with pq.ParquetFile(tmp_path / 'export' / 'occurrences.parquet') as occ_pf:
        assert occ_pf.metadata.num_row_groups == 3
        assert occ_pf.metadata.row_group(0).num_rows == 2048
        assert occ_pf.metadata.row_group(1).num_rows == 2048
        assert occ_pf.metadata.row_group(2).num_rows == 404

    # Verify facet summary
    fmt_facets = facet_summary(sources_pin, facet_set='sources_facets', column='format')
    assert fmt_facets == {'values': {'pdf': 2}, 'null_count': 1}


def test_conditional_manifest_pointer_uses_single_conditional_put_without_readback():
    calls = []

    class FakeS3:
        def put_object(self, **kwargs):
            calls.append(('put', kwargs))
            if kwargs.get('IfMatch') == 'stale-etag':
                raise ClientError(
                    {'Error': {'Code': 'PreconditionFailed', 'Message': 'ETag mismatch'}},
                    'PutObject',
                )
            return {'ETag': '"new-etag-1"'}

        def get_object(self, **kwargs):
            calls.append(('get', kwargs))
            raise AssertionError('publish_manifest_pointer must not call get_object readback')

    client = FakeS3()
    pointer = {'version': 1, 'catalog_id': 'abc', 'manifest': 'releases/123/manifest.json'}

    # Initial creation uses IfNoneMatch='*'
    receipt1 = publish_manifest_pointer(client, bucket='test-bucket', pointer=pointer)
    assert receipt1.bucket == 'test-bucket'
    assert receipt1.key == 'viewer-publications/manifest.json'
    assert receipt1.etag == '"new-etag-1"'
    assert len(calls) == 1
    assert calls[0][1]['IfNoneMatch'] == '*'
    assert 'IfMatch' not in calls[0][1]

    # Pointer advance uses IfMatch=expected_etag
    receipt2 = publish_manifest_pointer(
        client,
        bucket='test-bucket',
        pointer=pointer,
        expected_etag='"new-etag-1"',
    )
    assert receipt2.etag == '"new-etag-1"'
    assert len(calls) == 2
    assert calls[1][1]['IfMatch'] == '"new-etag-1"'
    assert 'IfNoneMatch' not in calls[1][1]

    # Stale ETag raises PreconditionFailed
    with pytest.raises(ClientError):
        publish_manifest_pointer(
            client,
            bucket='test-bucket',
            pointer=pointer,
            expected_etag='stale-etag',
        )

    # ConditionalManifestPublisher handles immutable asset deduplication + pointer update
    publisher = ConditionalManifestPublisher(client, bucket='test-bucket')
    asset_receipt = publisher.put_immutable_asset(
        'viewer-publications/releases/123/viewer-v2/sources.parquet',
        b'parquet-bytes',
    )
    assert asset_receipt.bytes == len(b'parquet-bytes')
