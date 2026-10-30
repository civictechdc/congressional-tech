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
    from viewer_publication.archive_schema import build_schema
    assert json.loads((root / 'schema.json').read_text()) == build_schema([f['name'] for f in manifest['files']])
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


def test_recovery_without_an_import_record_keeps_an_unknown_date(engine, tmp_path):
    from viewer_publication.archive_fixture import build_fixture_release
    value=json.loads((ROOT/'model/fixtures/hand-release.json').read_text())
    for document in value['documents']:
        if document.get('recovery'):document['recovery']['imported_at']=None
    fixture=tmp_path/'unknown-recovery-date.json';fixture.write_text(json.dumps(value))
    output=tmp_path/'release'
    build_fixture_release(fixture,output=output,scratch=tmp_path/'jobs',engine=engine)
    recovered=pq.read_table(output/'recoveries.parquet').to_pylist()
    assert len(recovered)==3 and all(row['imported_at'] is None for row in recovered)
    registry=json.loads((output/'schema.json').read_text())
    recovery=next(entry for entry in registry['files'] if entry['name']=='recoveries.parquet')
    imported=next(column for column in recovery['columns'] if column['name']=='imported_at')
    assert imported['type']=='date32' and imported['nullable'] is True


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


def test_minmax_collision_witness_matches_distinct_with_nulls(engine, tmp_path):
    from congress_api.retention.provenance import json_input,run_job
    groups={'one':['a'],'two':['a','b'],'repeat':['a','a'],
        'one_null':[None,'a',None],'two_null':['a',None,'b'],
        'all_null':[None,None],'empty':['',None,''],'empty_other':['','a',None]}
    rows=[dict(group_name=group,label=value,
        flag=None if value is None else value=='b',
        amount=None if value is None else (2 if value=='b' else 1))
        for group,values in groups.items() for value in values]
    source=json_input(tmp_path,'collision_samples',rows,group_name='Utf8',label='Utf8',flag='Boolean',amount='Int64')
    fields=['label','flag','amount']
    sql='SELECT group_name,'+','.join(
        f'count(DISTINCT {field})>1 AS old_{field},((min({field})<>max({field})) IS TRUE) AS new_{field}'
        for field in fields)+' FROM collision_samples GROUP BY group_name ORDER BY group_name'
    result=run_job(tmp_path,engine,inputs=[source],steps=[],outputs=[],queries=[dict(name='collisions',sql=sql)])
    assert len(result['collisions'])==len(groups)
    for row in result['collisions']:
        for field in fields:assert row['old_'+field]==row['new_'+field],(row,field)
    assert next(row for row in result['collisions'] if row['group_name']=='two_null')['new_label'] is True
    assert next(row for row in result['collisions'] if row['group_name']=='all_null')['new_label'] is False
