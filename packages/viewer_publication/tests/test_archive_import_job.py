"""Pinned Parquet commits unchanged as a fresh native generation, read back by key and value."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import file_pin

SCHEMA={'type':'struct','schema-id':0,'identifier-field-ids':[1,2,3],'fields':[
    {'id':1,'name':'record_sha','required':True,'type':'fixed[32]'},
    {'id':2,'name':'source','required':True,'type':'string'},
    {'id':3,'name':'parser_version','required':True,'type':'string'},
    {'id':4,'name':'status','required':False,'type':'string'},
    {'id':5,'name':'retrieved_at','required':False,'type':'timestamptz'}]}
# A plain pyarrow writer declares every field nullable and names the zone UTC, as the
# publish_v21 inputs do; the engine reads timestamptz back as +00:00.
ROWS=pa.table({'record_sha':pa.array([b'a'*32,b'b'*32],type=pa.binary(32)),
    'source':['house_xml','mods'],'parser_version':['old-1','old-2'],'status':['completed',None],
    'retrieved_at':pa.array([1_700_000_000_000_000,None],type=pa.timestamp('us',tz='UTC'))})


def _spec(tmp_path,source,**overrides):
    schema=tmp_path/'schema.json';schema.write_text(json.dumps(SCHEMA))
    value=dict(version=1,catalog_root=str(tmp_path/'catalog'),work=str(tmp_path/'work'),
        location=str(tmp_path/'data'),definition='import:fixture',provenance={'writer':'pyarrow fixture'},
        create_namespace=True,tables={'meeting_records':dict(
            source=dict(path=str(source),**file_pin(source)),schema=dict(path=str(schema),**file_pin(schema)),
            partition_spec=None,table=dict(namespace=['archive'],name='meeting_records_fixture'))})
    value.update(overrides)
    path=tmp_path/'import.json';path.write_text(json.dumps(value));return path


def test_import_commits_rows_unchanged_and_verifies_them(tmp_path):
    from viewer_publication.archive_import_job import execute,load_spec
    from congress_api.lake.maintenance import verify_generations
    from docspec_client.client import NativeDatasets
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    report=execute(load_spec(_spec(tmp_path,source)))
    entry=report['tables']['meeting_records']
    assert report['status']=='executed' and entry['verified'] and entry['pin']['snapshot'] is not None
    assert entry['keys']==['record_sha','source','parser_version']
    changed=tmp_path/'changed.parquet'
    pq.write_table(ROWS.set_column(3,'status',pa.array(['completed','error'])),changed)
    with pytest.raises(ValueError,match='typed rows'):
        verify_generations(dict(kind='parquet',path=str(changed),**file_pin(changed)),entry['pin'],
            keys=entry['keys'],engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            work=tmp_path/'unequal',exact=False)


def test_import_refuses_a_changed_source_before_any_effect(tmp_path):
    from viewer_publication.archive_import_job import execute,load_spec
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    spec=load_spec(_spec(tmp_path,source))
    pq.write_table(ROWS.slice(0,1),source)
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not (tmp_path/'work').exists() and not (tmp_path/'catalog').exists()


def test_import_refuses_a_changed_origin_before_any_effect(tmp_path):
    from viewer_publication.archive_import_job import execute,load_spec
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    origin=tmp_path/'origin.json';origin.write_text(json.dumps(dict(version=1,input='meeting_records')))
    path=_spec(tmp_path,source);value=json.loads(path.read_text())
    value['tables']['meeting_records']['producer']=dict(path=str(origin),**file_pin(origin));path.write_text(json.dumps(value))
    spec=load_spec(path);origin.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='producer does not match its pin'):execute(spec)
    assert not (tmp_path/'work').exists() and not (tmp_path/'catalog').exists()


def test_import_spec_requires_a_location_matching_its_catalog(tmp_path):
    from viewer_publication.archive_import_job import load_spec
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    with pytest.raises(ValueError,match='local location'):
        load_spec(_spec(tmp_path,source,location='s3://bucket/prefix'))
    with pytest.raises(ValueError,match='s3 location'):
        load_spec(_spec(tmp_path,source,catalog_root=None))


def test_import_adopts_an_empty_table_and_refuses_one_with_rows(tmp_path):
    from viewer_publication.archive_import_job import execute,load_spec
    from congress_api.lake.tables import create_table
    from docspec_client.client import NativeDatasets
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    spec=load_spec(_spec(tmp_path,source))
    item=spec['tables']['meeting_records']
    # An interrupted run: the table was created, the append never committed.
    create_table(engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'interrupted',
        catalog_root=spec['catalog_root'],table=item['table'],schema=SCHEMA,
        location=spec['location']+'/'+item['table']['name'],create_namespace=True)
    report=execute(spec)
    assert report['adopted_empty']==['meeting_records'] and report['tables']['meeting_records']['verified']
    again=load_spec(_spec(tmp_path,source,work=str(tmp_path/'again')))
    with pytest.raises(ValueError,match='already holds rows'):execute(again)


def test_import_writes_a_producer_record_that_carries_the_producing_jobs_record(tmp_path,monkeypatch):
    """Gate 5: Basin snapshots are made by the import, which names itself and embeds the
    record of the job that produced the rows; without an origin it writes none."""
    import congress_api.retention.writer_identity as identity
    from viewer_publication.archive_import_job import IMPORT_JOB,execute,load_spec
    monkeypatch.setattr(identity,'writer_identity',lambda root,job:dict(job=job,commit='c'*40,lockfile_digest='d'*64))
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    origin=tmp_path/'origin.json';origin.write_text(json.dumps(dict(version=1,input='meeting_records',job='daily',commit='e'*40)))
    path=_spec(tmp_path,source);value=json.loads(path.read_text())
    value['tables']['meeting_records']['producer']=dict(path=str(origin),**file_pin(origin));path.write_text(json.dumps(value))
    report=execute(load_spec(path))
    record=json.loads(open(report['producers']['meeting_records']['path']).read())
    assert record['job']==IMPORT_JOB and record['commit']=='c'*40
    assert record['selector']==report['tables']['meeting_records']['pin']
    assert record['origin']['record']['commit']=='e'*40 and record['origin']['pin']['sha256']==file_pin(origin)['sha256']
    (tmp_path/'bare').mkdir();bare=execute(load_spec(_spec(tmp_path/'bare',source)))
    assert bare['producers']['meeting_records']=={'unavailable':'no origin producer record was pinned'}


def test_import_accepts_explorer_tables_and_chains_their_producers(tmp_path,monkeypatch):
    """The seven-table release can copy both Explorer inputs and preserve gate 5's origin chain."""
    import congress_api.retention.writer_identity as identity
    from viewer_publication.archive_import_job import IMPORT_JOB,execute,load_spec
    monkeypatch.setattr(identity,'writer_identity',lambda root,job:dict(job=job,commit='c'*40,lockfile_digest='d'*64))
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    path=_spec(tmp_path,source);value=json.loads(path.read_text())
    meeting=value['tables'].pop('meeting_records')
    for name in ('video_records','committee_records'):
        origin=tmp_path/(name+'-origin.json')
        origin.write_text(json.dumps(dict(version=1,input=name,job='archive_backfill_job.py',commit='e'*40)))
        value['tables'][name]=dict(meeting,table=dict(namespace=['archive'],name=name+'_fixture'),
            producer=dict(path=str(origin),**file_pin(origin)))
    path.write_text(json.dumps(value))
    report=execute(load_spec(path))
    assert set(report['tables'])=={'video_records','committee_records'}
    for name,entry in report['tables'].items():
        assert entry['verified'] and entry['keys']==['record_sha','source','parser_version']
        record=json.loads(open(report['producers'][name]['path']).read())
        assert record['job']==IMPORT_JOB and record['selector']==entry['pin']
        assert record['origin']['record']['input']==name
