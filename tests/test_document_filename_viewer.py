import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
spec = importlib.util.spec_from_file_location('filename_viewer', SCRIPT)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)
from congress_api.retention import document_index as index



def catalog_from_sources(tmp_path, sources):
    rows = []
    for name, url, body, media, status in sources:
        row = dict.fromkeys(viewer.LIST_COLUMNS)
        row.update(filename=name, source_url=url, body_key=body,
                   extension=['pdf'] if name.endswith('.pdf') else None,
                   media_type=[media] if media else None, http_status=[status] if status else None)
        rows.append(row)
    schema = pa.schema([(field, pa.string() if field in ('filename', 'source_url', 'body_key')
                         else pa.list_(pa.string())) for field in viewer.LIST_COLUMNS])
    path = tmp_path / 'test.parquet'
    index.write_document_indexes(path, rows, schema)
    return viewer.Catalog(path)


def test_only_download_parameters_group_not_document_ids_or_other_paths():
    key = index.entry_key
    assert key('statement', 'https://x.test/a/statement', 0) == key(
        'statement&download=1', 'https://x.test/a/statement&download=1', 1)
    assert key('statement', 'https://x.test/a/statement?download=1', 2) == key(
        'statement', 'https://x.test/a/statement', 0)
    assert key('statement', 'https://x.test/a/statement?id=1', 0) != key(
        'statement', 'https://x.test/a/statement?id=2', 1)
    assert key('download', 'https://x.test/download?download=file1', 0) != key(
        'download', 'https://x.test/download?download=file2', 1)
    assert key('statement', 'https://x.test/a/statement', 0) != key(
        'statement', 'https://x.test/b/statement', 1)
    assert key('statement', 'https://x.test/a/statement', 0) != key(
        'statement', 'https://y.test/a/statement', 1)
    assert key('statement', None, 0) != key('statement', None, 1)
    assert index.display_filename('report.pdf?download=1') == 'report.pdf'
    assert index.display_filename('report&download=1') == 'report'
    assert index.display_filename('Oil&Gas.pdf') == 'Oil&Gas.pdf'


def test_grouping_prefers_saved_pdf_and_retains_raw_rows_and_filter_behavior(tmp_path):
    rows = []
    for name, url, body, media in [
        ('statement', 'https://x.test/statement', 'html-body', 'text/html'),
        ('statement&download=1', 'https://x.test/statement&download=1', 'pdf-body', 'application/pdf'),
        ('statement', 'https://y.test/statement', None, None),
    ]:
        row = dict.fromkeys(viewer.LIST_COLUMNS)
        row.update(filename=name, source_url=url, body_key=body,
            media_type=[media] if media else None, http_status=['200'] if body else None)
        rows.append(row)
    schema = pa.schema([(field, pa.string() if field in ('filename', 'source_url', 'body_key')
                         else pa.list_(pa.string())) for field in viewer.LIST_COLUMNS])
    path = tmp_path / 'test.parquet'
    index.write_document_indexes(path, rows, schema)
    catalog = viewer.Catalog(path)
    result = catalog.search({'q': 'statement'})
    assert result['total'] == 2
    grouped = next(r for r in result['rows'] if r['source_count'] == 2)
    assert grouped['_row'] == 1 and grouped['filename'] == 'statement'
    assert grouped['format'] == ['html', 'pdf']
    assert catalog.record(1)['filename'] == 'statement&download=1'
    assert len(catalog.entry(1)['sources']) == 2
    # Filters match any source; the persisted canonical row stays consistent.
    assert catalog.search({'format': 'html'})['rows'][0]['_row'] == 1
    assert catalog.search({'format': 'pdf'})['rows'][0]['_row'] == 1
    assert catalog.search({'retained': 'no'})['total'] == 1
    assert catalog.search({'q': 'nothing'})['total'] == 0
    assert catalog.search({'page': '999', 'limit': '1'})['page'] == 2


def test_identical_download_and_direct_pdf_share_one_entry_with_both_sources(tmp_path):
    name = '01-14-25_nom-transcript'
    endpoint = 'https://www.armed-services.senate.gov/download/' + name
    direct = 'https://www.armed-services.senate.gov/imo/media/doc/' + name + '.pdf'
    catalog = catalog_from_sources(tmp_path, [
        (name, endpoint, 'same-pdf-hash', 'application/pdf', '200'),
        (name + '.pdf', direct, 'same-pdf-hash', 'application/pdf', '200'),
    ])
    result = catalog.search({'q': name})
    assert result['total'] == 1
    row, = result['rows']
    assert row['filename'] == name + '.pdf'
    assert row['source_url'] == direct and row['source_count'] == 2
    assert {r['source_url'] for r in catalog.entry(row['_row'])['sources']} == {endpoint, direct}
    assert catalog.record(0)['filename'] == name  # Original row links still work.
    assert catalog.record(1)['filename'] == name + '.pdf'
    assert catalog.search({'q': '/download/', 'field': 'source_url'})['total'] == 1


@pytest.mark.parametrize('order', [(0, 1, 2), (2, 0, 1), (1, 2, 0)])
def test_html_download_variant_and_identical_direct_pdf_join_transitively(tmp_path, order):
    sources = [
        ('statement', 'https://x.test/download/statement', 'html', 'text/html', '200'),
        ('statement&download=1', 'https://x.test/download/statement&download=1', 'pdf', 'application/pdf', '200'),
        ('statement.pdf', 'https://x.test/files/statement.pdf', 'pdf', 'application/pdf', '200'),
    ]
    catalog = catalog_from_sources(tmp_path, [sources[i] for i in order])
    result = catalog.search({})
    assert result['total'] == 1
    row, = result['rows']
    assert row['filename'] == 'statement.pdf' and row['source_count'] == 3
    assert row['format'] == ['html', 'pdf']
    assert catalog.search({'format': 'html'})['rows'][0]['filename'] == 'statement.pdf'


def test_viewer_reads_persisted_identity_and_preference_without_reinterpreting_sources(tmp_path):
    catalog_from_sources(tmp_path, [
        ('endpoint', 'https://x.test/download', 'pdf', 'application/pdf', '200'),
        ('file.pdf', 'https://x.test/file.pdf', 'pdf', 'application/pdf', '200'),
    ])
    path = tmp_path / 'documents.parquet'
    table = pq.read_table(path)
    field = table.schema.field('filename')
    table = table.set_column(table.schema.get_field_index('filename'), field, pa.array(['Chosen in root index.pdf']))
    pq.write_table(table, path)
    catalog = viewer.Catalog(tmp_path / 'test.parquet')
    row, = catalog.search({})['rows']
    assert row['filename'] == 'Chosen in root index.pdf'
    assert not hasattr(viewer, 'source_groups')
    assert not hasattr(viewer, 'source_priority')


def test_mixed_index_generations_fail_clearly(tmp_path):
    catalog_from_sources(tmp_path, [('file.pdf', 'https://x.test/file.pdf', 'pdf', 'application/pdf', '200')])
    path = tmp_path / 'documents.parquet'
    table = pq.read_table(path)
    pq.write_table(table.replace_schema_metadata({**table.schema.metadata, b'catalog_id': b'different'}), path)
    with pytest.raises(ValueError, match='different builds'):
        viewer.Catalog(tmp_path / 'test.parquet')


def test_missing_kind_filters_document_groups_and_combines_with_search(tmp_path):
    catalog_from_sources(tmp_path, [
        ('alias', 'https://x.test/alias', 'shared', 'application/pdf', '200'),
        ('typed.pdf', 'https://x.test/typed.pdf', 'shared', 'application/pdf', '200'),
        ('unknown.pdf', 'https://x.test/unknown.pdf', None, None, None),
        ('empty.pdf', 'https://x.test/empty.pdf', 'empty-kind', 'application/pdf', '200'),
    ])
    # One alias has no kind, but its document group is already classified.
    # Test both representations of an absent kind without changing grouping.
    for name in ('test.parquet', 'documents.parquet'):
        path = tmp_path / name
        table = pq.read_table(path)
        kinds = [['testimony'] if filename == 'typed.pdf' else [] if filename == 'empty.pdf' else None
                 for filename in table['filename'].to_pylist()]
        table = table.set_column(table.schema.get_field_index('document_kind'),
                                 table.schema.field('document_kind'), pa.array(kinds, type=pa.list_(pa.string())))
        pq.write_table(table, path)
    catalog = viewer.Catalog(tmp_path / 'test.parquet')
    result = catalog.search({'document_kind': '__null__'})
    assert result['total'] == 2
    assert {r['filename'] for r in result['rows']} == {'unknown.pdf', 'empty.pdf'}
    assert catalog.search({'document_kind': '__null__', 'q': 'alias'})['total'] == 0
    assert catalog.search({'document_kind': '__null__', 'q': 'unknown', 'retained': 'no'})['total'] == 1
    assert catalog.search({'document_kind': '__null__', 'format': 'pdf', 'retained': 'yes'})['total'] == 1
    assert catalog.search({'document_kind': '__null__', 'page': '999', 'limit': '1'})['page'] == 2
    assert catalog.search({'document_kind': 'testimony'})['total'] == 1
    assert catalog.search({})['total'] == 3


@pytest.mark.parametrize(('body1', 'body2', 'media', 'status'), [
    ('v1', 'v2', 'application/pdf', '200'),  # Same basename, different content.
    ('error', 'error', 'text/html', '200'),
    ('error', 'error', 'application/pdf', '404'),
    ('unknown', 'unknown', 'application/octet-stream', '200'),
    ('unknown', 'unknown', None, '200'),  # Filename extension is not a response type.
    ('unknown', 'unknown', 'application/pdf', None),
    (None, None, 'application/pdf', '200'),
])
def test_hash_grouping_never_hides_errors_unknowns_or_different_documents(tmp_path, body1, body2, media, status):
    catalog = catalog_from_sources(tmp_path, [
        ('statement.pdf', 'https://x.test/one/statement.pdf', body1, media, status),
        ('statement.pdf', 'https://x.test/two/statement.pdf', body2, media, status),
    ])
    assert catalog.search({})['total'] == 2
