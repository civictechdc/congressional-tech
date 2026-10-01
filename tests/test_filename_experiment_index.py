"""Preserve source assertions and meaningful distinctions when publishing metadata."""
from hashlib import sha256
import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index


def test_empty_successful_bodies_do_not_identify_unrelated_documents(tmp_path):
    empty = f'bodies/sha256/e3/{sha256(b"").hexdigest()}.gz'
    rows = [dict(body_key=empty, filename=f'{name}.pdf', source_url=f'https://x.test/{name}.pdf',
                 media_type=['application/pdf'], http_status=['200']) for name in ('a', 'b')]
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, rows, index.SOURCE_SCHEMA)
    sources = pq.read_table(path).to_pylist()
    documents = pq.read_table(path.with_name('documents.parquet')).to_pylist()
    assert len(documents) == 2
    assert len({row['document_id'] for row in sources}) == 2
    assert all(row['body_key'] == empty and row['http_status'] == ['200'] for row in sources)


def test_one_canonical_publication_code_in_tables_without_changing_engine(tmp_path):
    (tmp_path / 'indexes').mkdir()
    name = 'CHRG-119HHRG12345.pdf'
    before = index.Engine().extract(name)['metadata']
    assert before['publication_code'] == ['HHRG']
    assert before['publication_code_code'] == before['publication_type'] == ['hhrg']
    index.write_filename_metadata(tmp_path, [dict(body_key=None, filename=name, source_url=None)], workers=1)
    for name in ('document-filenames.parquet', 'documents.parquet'):
        table = pq.read_table(tmp_path / 'indexes' / name)
        assert 'publication_code_code' not in table.column_names
        assert table['publication_type'].to_pylist() == [['hhrg']]
        assert table['publication_code'].to_pylist() == [['HHRG']]


def test_code_consolidation_keeps_distinct_or_unpaired_readings(tmp_path):
    fields = ['publication_code_code', 'publication_type', 'field_marker', 'field_marker_label',
              'version_number_token', 'stage_occurrence']
    schema = pa.schema([*index.SOURCE_SCHEMA, *[(field, index.STRINGS) for field in fields]])
    rows = [dict(filename='one.pdf', source_url='https://x.test/one.pdf', body_key=None,
                 publication_code_code=['hhrg'], field_marker=['field'], field_marker_label=['Field'],
                 version_number_token=['2'])]
    path = tmp_path / 'document-filenames.parquet'
    index.write_document_indexes(path, rows, schema)
    table = pq.read_table(path)
    assert table['publication_code_code'].to_pylist() == [['hhrg']]
    assert table['publication_type'].to_pylist() == [None]
    assert table['field_marker'].to_pylist() != table['field_marker_label'].to_pylist()
    assert table['version_number_token'].to_pylist() == [['2']]
    assert table['stage_occurrence'].to_pylist() == [None]


def test_literal_and_source_congress_and_document_types_stay_separate(tmp_path):
    (tmp_path / 'indexes').mkdir()
    sources = [dict(body_key=None, filename='BILLS-107hr2323ih.pdf', source_url=None,
                    source_congress=['114'], source_document_type=['Bills and Resolutions']),
               dict(body_key=None, filename='JaneDoe.pdf', source_url=None,
                    source_document_type=['Witness Statement'])]
    index.write_filename_metadata(tmp_path, sources, workers=1)
    rows = pq.read_table(tmp_path / 'indexes/document-filenames.parquet').to_pylist()
    bill, person = rows
    assert bill['congress'] == ['107'] and bill['source_congress'] == ['114']
    assert person['source_document_type'] == ['Witness Statement']
    assert person['document_kind'] == ['witness-statement']
    assert person['document_kind_source'] == ['source_document_type']
    assert not index.Engine().extract('JaneDoe.pdf')['metadata'].get('document_kind')


def test_old_publication_field_filter_uses_canonical_column(tmp_path):
    (tmp_path / 'indexes').mkdir()
    sources = [dict(body_key=None, filename='CHRG-119hhrg12345.pdf', source_url=None)]
    index.write_filename_metadata(tmp_path, sources, workers=1)
    path = tmp_path / 'indexes/document-filenames.parquet'
    # Ensure the fixture exercises the new schema even against the old writer.
    for target in (path, path.with_name('documents.parquet')):
        table = pq.read_table(target)
        if 'publication_code_code' in table.column_names:
            pq.write_table(table.drop(['publication_code_code']), target)
    script = Path(__file__).parents[1] / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
    spec = importlib.util.spec_from_file_location('experiment_viewer', script)
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    catalog = viewer.Catalog(path)
    assert catalog.search({'field': 'publication_code_code', 'q': 'hhrg'})['total'] == 1


def test_govinfo_summary_endpoint_keeps_package_identity_without_document_subject():
    row = index.extract(('summary', 'https://api.govinfo.gov/packages/CHRG-118hhrg58134/summary'))
    assert row == {'source_record_identifier': ['CHRG-118hhrg58134'],
                   'source_record_type': ['package-summary']}
    ordinary = index.extract(('summary.pdf', 'https://example.test/summary.pdf'))
    assert 'source_record_type' not in ordinary
    assert ordinary['extension'] == ['pdf']


def test_known_error_endpoints_are_not_document_subjects():
    for name, url in [('Error.aspx', 'https://docs.house.gov/committee/Error/Error.aspx?Code=404'),
                      ('error', 'https://www.govinfo.gov/error')]:
        expected = {'source_record_type': ['error-page']}
        if name == 'Error.aspx':
            expected['extension'] = ['aspx']
        assert index.extract((name, url)) == expected
    assert 'source_record_type' not in index.extract(('Error.pdf', 'https://example.test/Error.pdf'))
