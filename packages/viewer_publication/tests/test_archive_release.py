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


def test_hand_release_covers_the_reader_outcomes(engine, tmp_path):
    from viewer_publication.archive_release import build_fixture_release

    fixture = ROOT / 'model/fixtures/hand-release.json'
    expected = json.loads(fixture.read_text())['expected']
    output = tmp_path / 'release'
    manifest = build_fixture_release(fixture, output=output, scratch=tmp_path / 'jobs', engine=engine)
    checked_manifest(output, manifest)
    rows = pq.read_table(output / 'list.parquet').to_pylist()
    assert len(rows) == expected['list_rows']
    assert sum(not row['hidden'] for row in rows) == expected['visible_rows']
    assert [row['filename'] for row in rows] == ['Agenda.pdf', 'Hearing excerpt.pdf', 'Hidden.pdf',
        'Recovered.pdf', 'Record.pdf', 'Record.pdf', 'Substitute.pdf']
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
    list_fields = ['format', 'document_kind', 'document_family', 'committee_code', 'congress',
        'date_token', 'state_retrieved_at', 'source_link_label', 'source_page_url', 'source_meeting_id']
    for row in rows:
        row.update({field: [] for field in list_fields})
        row.update(format=['pdf'], document_kind=['statement'], congress=['118'],
                   date_token=['2024-05-01'], source_link_label=['Published statement'])
    schema = pa.schema([pa.field(name, pa.string()) for name in ['document_id', 'source_id', 'body_key', 'filename', 'source_url']]
        + [pa.field(name, pa.list_(pa.string())) for name in ['body_keys', *list_fields]])
    documents = tmp_path / 'documents.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), documents)
    filenames = tmp_path / 'filenames.parquet'
    pq.write_table(pa.Table.from_pylist([{k: v for k, v in row.items() if k != 'body_keys'} for row in rows]), filenames)
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.table({'body_key': [body], 'bytes': pa.array([100], pa.int64()), 'media_type': ['application/pdf']}), captures)
    committees = tmp_path / 'committees.parquet'
    pq.write_table(pa.table({'system_code': ['hsag00'], 'name': ['Committee on Agriculture'], 'chamber': ['house']}), committees)
    output = tmp_path / 'release'
    manifest = convert_catalog(documents, filenames, captures, committees, catalog_id='fixture-catalog',
        output=output, scratch=tmp_path / 'jobs', engine=engine)
    checked_manifest(output, manifest)
    assert pq.ParquetFile(output / 'list.parquet').metadata.num_rows == 2
    assert pq.read_table(output / 'links.parquet').to_pylist() == [{'link_key': bytes([17]) * 8, 'list_row': 0}]
    assert [row['saved_bytes'] for row in pq.read_table(output / 'detail.parquet').to_pylist()] == [100, 100]
    assert manifest['origin']['catalog_id'] == 'fixture-catalog'
