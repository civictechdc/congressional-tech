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


def test_failed_response_and_paired_origin_are_visible_and_searchable(tmp_path):
    (tmp_path / 'indexes').mkdir()
    row = dict(body_key='bad-body', filename='SCA_Berman.pdf', source_url='https://x.test/a',
               http_status=['200'], media_type=['application/pdf'], response_usable=['false'],
               response_format=['pdf_missing_eof'], source_occurrences=[{
                   'source_page_url': ['https://committee.test/hearing'], 'source_link_label': ['Amy Berman - Article']}])
    index.write_filename_metadata(tmp_path, [row], workers=1)
    catalog = viewer.Catalog(tmp_path / 'indexes/document-filenames.parquet')
    assert catalog.search({'document_kind': '__null__'})['total'] == 0
    result = catalog.search({'scope': 'capture-records', 'field': 'source_occurrences', 'q': 'Amy Berman'})
    assert result['total'] == 1
    assert result['rows'][0]['response_format'] == ['pdf_missing_eof']
    assert result['rows'][0]['response_usable'] == ['false']
    assert catalog.record(result['rows'][0]['_row'])['source_occurrences'][0]['source_link_label'] == ['Amy Berman - Article']


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


def test_family_filters_specific_kinds_and_source_fallbacks(tmp_path):
    (tmp_path / 'indexes').mkdir()
    rows = [
        dict(filename='Lee Letter of Support for Smith.pdf', source_url='https://x.test/letter', body_key=None),
        dict(filename='Lee Opening Statement.pdf', source_url='https://x.test/opening', body_key=None),
        dict(filename='123.pdf', source_url='https://x.test/native', body_key=None,
             source_document_type=['Witness Statement']),
        dict(filename='Lee Support for Smith.pdf', source_url='https://x.test/unknown', body_key=None),
    ]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    catalog = viewer.Catalog(tmp_path / 'indexes/document-filenames.parquet')
    statements = catalog.search({'document_family': 'statement'})
    assert statements['total'] == 2
    assert {tuple(r['document_kind']) for r in statements['rows']} == {('opening-statement',), ('witness-statement',)}
    assert catalog.search({'document_family': 'letter'})['total'] == 1
    assert catalog.search({'document_family': 'statement', 'document_kind': 'opening-statement'})['total'] == 1
    assert catalog.search({'document_family': 'letter', 'document_kind': 'opening-statement'})['total'] == 0
    assert catalog.search({'document_family': '__null__'})['total'] == 1
    assert catalog.search({'document_family': '__null__', 'q': 'Smith'})['total'] == 1
    for row in statements['rows']:
        assert row['document_family'] == ['statement']
        assert catalog.record(row['_row'])['document_family'] == ['statement']
    assert set(catalog.info['facets']['document_family']) == {'letter', 'statement'}


def test_nomination_support_family_keeps_specific_forms_and_drops_null_filter(tmp_path):
    (tmp_path / 'indexes').mkdir()
    parent = 'https://www.judiciary.senate.gov/committee-activity/hearings/nominations'
    rows = [dict(filename=name, body_key=None, source_url=f'https://www.judiciary.senate.gov/download/{i}',
                 source_occurrences=[dict(source_original_page_url=[parent], source_page_title=['Nominations'],
                     source_link_label=[name], source_link_url=[f'https://www.judiciary.senate.gov/download/{i}'],
                     source_occurrence_scope=['anchor'])])
            for i, name in enumerate(['Aramayo Support for de Alba.pdf', 'Maley Letter of Support for Kolar.pdf',
                                      'Labor Unions Statement of Support for Berner.pdf', 'Group Support for S. 2754.pdf'])]
    index.write_filename_metadata(tmp_path, rows, workers=1)
    catalog = viewer.Catalog(tmp_path / 'indexes/document-filenames.parquet')
    result = catalog.search({'document_family': 'nomination-support'})
    assert result['total'] == 3
    assert {tuple(row['document_kind']) for row in result['rows']} == {
        ('nomination-support',), ('letter-of-support',), ('statement',)}
    assert catalog.search({'document_kind': 'nomination-support'})['total'] == 1
    assert catalog.search({'document_family': 'nomination-support', 'document_kind': '__null__'})['total'] == 0
    assert catalog.search({'q': 'Aramayo', 'document_kind': '__null__'})['total'] == 0
    assert 'nomination-support' in catalog.info['facets']['document_family']


def test_family_recomputes_after_source_kind_is_removed():
    row = dict(document_kind=None, document_family=['letter'], source_document_type=['other'])
    index.fill_document_kind(row)
    assert row['document_family'] is None
    row['source_document_type'] = ['Witness Statement']
    index.fill_document_kind(row)
    assert row['document_kind'] == ['witness-statement']
    assert row['document_family'] == ['statement']


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


def test_default_document_scope_keeps_capture_records_available_separately(tmp_path):
    catalog_from_sources(tmp_path, [
        ('unknown.pdf', 'https://x.test/unknown.pdf', None, None, None),
        ('123.xml', None, 'meeting', 'text/xml', None),
        ('123.none', None, 'marker', None, None),
        ('error.pdf', None, 'html-error', 'text/html', None),
    ])
    roles = {'unknown.pdf': 'document', '123.xml': 'source-record',
             '123.none': 'capture-state', 'error.pdf': 'error-response'}
    for filename in ('test.parquet', 'documents.parquet'):
        path = tmp_path / filename
        table = pq.read_table(path)
        table = table.set_column(table.schema.get_field_index('record_role'),
            table.schema.field('record_role'), pa.array([[roles[x]] for x in table['filename'].to_pylist()]))
        pq.write_table(table, path)
    catalog = viewer.Catalog(tmp_path / 'test.parquet')
    assert catalog.search({'document_kind': '__null__'})['total'] == 1
    assert catalog.search({'scope': 'all', 'document_kind': '__null__'})['total'] == 4
    assert catalog.search({'scope': 'capture-records'})['total'] == 3
    assert catalog.search({'scope': 'capture-records', 'q': '123.none'})['rows'][0]['record_role'] == ['capture-state']
    assert catalog.info['documents'] == 1
    assert catalog.info['capture_records'] == 3
    with pytest.raises(ValueError, match='scope'):
        catalog.search({'scope': 'typo'})


def test_recovered_publisher_name_is_searchable_without_losing_literal_cache_search(tmp_path):
    name = 'HHRG-119-IF00-WList-20250101.pdf'
    cache = 'house_123_documents_HHRG_119_IF00_WList_20250101_pdf'
    url = f'https://www.congress.gov/119/meeting/house/123/documents/{name}'
    row = dict(body_key=None, filename=cache, source_url=None,
               recovered_filename=[name], recovered_source_url=[url], document_kind=['witness-list'])
    schema = pa.schema([*index.SOURCE_SCHEMA, ('recovered_filename', index.STRINGS),
                        ('recovered_source_url', index.STRINGS), ('document_kind', index.STRINGS),
                        ('congress', index.STRINGS), ('extension', index.STRINGS)])
    index.write_document_indexes(tmp_path / 'test.parquet', [row], schema)
    catalog = viewer.Catalog(tmp_path / 'test.parquet')
    assert catalog.search({'q': name})['total'] == 1
    assert catalog.search({'q': cache})['total'] == 1
    assert catalog.search({'q': name})['rows'][0]['filename'] == name
    assert catalog.record(0)['filename'] == cache
