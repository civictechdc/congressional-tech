"""F0 uses the native job runner for release rows, joins and file layout."""
from hashlib import md5, sha256
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets


ROOT = Path(__file__).parents[3]


@pytest.fixture
def engine():
    # This is the same explicit runtime configuration the converter CLI takes.
    # The runner supplies the compiled, pinned local engine; no substitute path.
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def checked_manifest(root, manifest):
    assert json.loads((root / 'manifest.json').read_text()) == manifest
    for item in manifest['files']:
        data = (root / item['name']).read_bytes()
        assert sha256(data).hexdigest() == item['sha256']
        assert md5(data).hexdigest() == item['md5']
        assert len(data) == item['size']
        if item['name'].endswith('.parquet'):
            file = pq.ParquetFile(root / item['name'])
            assert file.metadata.num_rows == item['rows']
            assert file.metadata.created_by == 'docspec archive release v1'
    assert manifest['origin']['kind'] in {'converted_catalog', 'hand_fixture'}


def test_shared_legacy_meeting_selector_keeps_url_variants(engine, tmp_path):
    from congress_api.retention.provenance import json_input, run_job
    from viewer_publication.archive_format import legacy_meeting_keys

    urls = [
        'https://docs.house.gov/meetings/AG/AG00/20261020/000123/a.pdf?eventID=999',
        'https://publisher.test/a?EVENTID=000456',
        'https://publisher.test/house-event/789/a.pdf',
        'https://publisher.test/senate-event/790/a.pdf',
        'https://publisher.test/joint-event/791/a.pdf',
        'https://publisher.test/unrelated.pdf', None,
        'https://publisher.test/a?eventid=999999999999999999999999999999',
    ]
    source = json_input(tmp_path, 'urls', [dict(ordinal=i, url=url) for i, url in enumerate(urls)],
                        ordinal='Int64', url='Utf8')
    result = run_job(tmp_path, engine, inputs=[source], steps=[], outputs=[], queries=[
        dict(name='meetings', sql=f'SELECT {legacy_meeting_keys("url")} AS keys FROM urls ORDER BY ordinal')])
    assert [row['keys'] for row in result['meetings']] == [
        ['123'], ['456'], ['789'], ['790'], ['791'], [], [], []]


def test_hand_release_covers_the_reader_outcomes(engine, tmp_path):
    from viewer_publication.archive_fixture import build_fixture_release

    fixture = ROOT / 'model/fixtures/hand-release.json'
    expected = json.loads(fixture.read_text())['expected']
    output = tmp_path / 'release'
    manifest = build_fixture_release(fixture, output=output, scratch=tmp_path / 'jobs', engine=engine)
    checked_manifest(output, manifest)
    rows = pq.read_table(output / 'list.parquet').to_pylist()
    assert len(rows) == expected['list_rows']
    assert sum(not row['hidden'] for row in rows) == expected['visible_rows']
    assert [row['filename'] for row in rows] == ['Agenda.pdf', 'Hearing excerpt.pdf', 'Hidden.pdf',
        'Record.pdf', 'Record.pdf', 'Recovered.pdf', 'Substitute.pdf']
    assert 'document_id' not in rows[0]
    details = pq.read_table(output / 'detail.parquet').to_pylist()
    assert [item['format'] for item in details[0]['alternates']] == ['xml']
    links = pq.read_table(output / 'links.parquet').to_pylist()
    assert next(row['list_row'] for row in links if row['link_key'] == bytes([17]) * 8) == 0
    assert rows[2]['hidden'] and any(row['list_row'] == 2 for row in links)
    assert sorted(row['kind'] for row in pq.read_table(output / 'recoveries.parquet').to_pylist()) == sorted(expected['recovery_kinds'])
    assert pq.read_table(output / 'meetings.parquet').to_pylist()[0]['title'] == expected['meeting_title']
    lookup = pq.read_table(output / 'urls.parquet').to_pylist()
    key = sha256(b'lookup:fixture.test/record.pdf').digest()[:8]
    assert [row['list_row'] for row in lookup if row['lookup_key'] == key] == expected['version_lookup_rows']
    assert set(manifest['facet_counts'][0]) == {'facet', 'value', 'count'}


def test_converted_catalog_keeps_rows_and_shared_body_keys_choose_first(engine, tmp_path):
    from viewer_publication.archive_release import convert_catalog

    body = 'bodies/sha256/11/' + '11' * 32 + '.gz'
    rows = [dict(document_id='a' * 64, source_id='one', body_key=body, body_keys=[body],
        filename='A.pdf', source_url='https://fixture.test/a.pdf'),
        dict(document_id='b' * 64, source_id='two', body_key=body, body_keys=[body],
        filename='Z.pdf', source_url='https://fixture.test/z.pdf')]
    rows.append(dict(rows[0], document_id='c' * 64, source_id='three', body_key=None, body_keys=[], filename='Metadata.json', source_url='https://fixture.test/meta.json'))
    list_fields = ['format', 'document_kind', 'document_family', 'committee_code', 'congress',
        'date_token', 'state_retrieved_at', 'source_link_label', 'source_page_url', 'source_meeting_id']
    for row in rows:
        row.update({field: [] for field in list_fields})
        row.update(format=['pdf'], document_kind=['statement'], congress=['118'], committee_code=['AG'],
                   date_token=['2024-05-01'], source_link_label=['Published statement'],
                   state_retrieved_at=['2020-01-02T00:00:00Z'])
    rows[1]['date_token'] = ['2024-05-01', '2024-05-02']
    schema = pa.schema([pa.field(name, pa.string()) for name in ['document_id', 'source_id', 'body_key', 'filename', 'source_url']]
        + [pa.field(name, pa.list_(pa.string())) for name in ['body_keys', *list_fields]])
    documents = tmp_path / 'documents.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), documents)
    filenames = tmp_path / 'filenames.parquet'
    file_rows = [{k: v for k, v in row.items() if k != 'body_keys'} for row in rows]
    file_rows += [dict(file_rows[0], source_id='duplicate-name', filename='Other.pdf'),
                  dict(file_rows[0], source_id='0-earlier-key', body_key=None, source_url='https://fixture.test/earlier.pdf')]
    pq.write_table(pa.Table.from_pylist(file_rows,
        schema=pa.schema([field for field in schema if field.name != 'body_keys'])), filenames)
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.table({'body_key': [body], 'bytes': pa.array([100], pa.int64()), 'media_type': ['application/pdf']}), captures)
    committees = tmp_path / 'committees.parquet'
    pq.write_table(pa.table({'system_code': ['hsag00'], 'name': ['Committee on Agriculture'], 'chamber': ['house']}), committees)
    output = tmp_path / 'release'
    manifest = convert_catalog(documents, filenames, captures, committees, catalog_id='fixture-catalog',
        output=output, scratch=tmp_path / 'jobs', engine=engine)
    checked_manifest(output, manifest)
    assert pq.ParquetFile(output / 'list.parquet').metadata.num_rows == 3
    assert pq.read_table(output / 'links.parquet').to_pylist() == [{'link_key': bytes([17]) * 8, 'list_row': 0}]
    assert [row['saved_bytes'] for row in pq.read_table(output / 'detail.parquet').to_pylist()] == [100, None, 100]
    listed = pq.read_table(output / 'list.parquet').to_pylist()
    assert listed[0]['committee_keys'] == ['hsag00'] and listed[0]['chambers'] == ['house']
    assert all(row['first_captured'] is None and row['date_kind'] == 'unknown' for row in listed)
    assert listed[0]['document_date'] is not None and listed[2]['document_date'] is None
    assert all(row['in_archive_since'] is None for row in pq.read_table(output / 'detail.parquet').to_pylist())
    details = pq.read_table(output / 'detail.parquet').to_pylist()
    assert all(details[1][field] is None for field in ['link_key', 'saved_body', 'saved_suffix', 'saved_media_type', 'saved_bytes'])
    sources = pq.read_table(output / 'sources.parquet').to_pylist()
    assert [(row['url'], row['is_saved'], row['ordinal']) for row in sources if row['list_row'] == 0] == [
        ('https://fixture.test/a.pdf', True, 0), ('https://fixture.test/earlier.pdf', False, 1)]
    assert details[0]['src_len'] == 2
    assert pq.read_table(output / 'committees.parquet').to_pylist()[0]['is_current'] is None
    assert manifest['origin']['catalog_id'] == 'fixture-catalog'


def test_rescued_committee_inventory_is_read_by_the_engine(engine, tmp_path):
    import gzip
    from viewer_publication.archive_release import committee_input

    path = tmp_path / 'inventory.gz'
    with gzip.open(path, 'wt') as out:
        out.write(json.dumps({'congress': 119, 'committee': {'systemCode': 'hsag00',
            'name': 'Agriculture', 'chamber': 'House', 'subcommittees': [
                {'systemCode': 'hsag03', 'name': 'Nutrition'}]}}) + '\n')
        out.write(json.dumps({'congress': 118, 'committee': {'systemCode': 'hsag00',
            'name': 'Older name', 'chamber': 'House'}}) + '\n')
    input_spec, steps = committee_input(path)
    spec = tmp_path / 'job.json'
    spec.write_text(json.dumps(dict(scratch=str(tmp_path / 'native'), inputs=[input_spec],
        steps=steps, outputs=[], queries=[dict(name='rows', sql='SELECT * FROM committee_source ORDER BY system_code') ])))
    rows = engine.run_job(spec)['queries'][0]['data']
    assert rows == [dict(system_code='hsag00', name='Agriculture', chamber='house'),
                    dict(system_code='hsag03', name='Nutrition', chamber='house')]
