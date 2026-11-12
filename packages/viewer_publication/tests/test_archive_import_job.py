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


def test_import_commits_rows_unchanged_and_verifies_them(tmp_path,monkeypatch):
    import congress_api.retention.writer_identity as identity
    from viewer_publication.archive_import_job import execute,load_spec
    from congress_api.lake.maintenance import verify_generations
    from docspec_client.client import NativeDatasets
    monkeypatch.setattr(identity,'writer_identity',lambda root,job:dict(job=job,commit='c'*40,lockfile_digest='d'*64))
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


@pytest.mark.parametrize('problem, expected', [
    ('delta_only', 'a staged delta cannot be the origin'),
    ('final_reconciliation_required', 'a staged delta cannot be the origin'),
    ('different_bytes', 'the Parquet origin does not match the import source pin'),
    ('different_table', 'the import origin names another table'),
    ('missing_selector', 'must name a Parquet artifact or native snapshot'),
    ('unknown_selector_kind', 'must name a Parquet artifact or native snapshot'),
    ('incomplete_native_selector', 'needs an exact native table pin'),
])
def test_import_refuses_incomplete_or_mismatched_origin_before_any_effect(tmp_path, problem, expected):
    from viewer_publication.archive_import_job import execute, load_spec

    source = tmp_path/'rows.parquet'
    pq.write_table(ROWS, source)
    path = _spec(tmp_path, source)
    value = json.loads(path.read_text())
    item = value['tables']['meeting_records']
    origin = dict(input='meeting_records', selector=dict(kind='parquet', **item['source']))
    if problem == 'different_bytes':
        origin['selector']['sha256'] = '0'*64
    elif problem == 'different_table':
        origin.update(input='video_records', selector={'kind': 'native_table', 'snapshot': 7})
    elif problem == 'missing_selector':
        origin.pop('selector')
    elif problem == 'unknown_selector_kind':
        origin['selector']['kind'] = 'unknown'
    elif problem == 'incomplete_native_selector':
        origin['selector'] = {'kind': 'native_table'}
    else:
        origin[problem] = True
    origin_path = tmp_path/'origin.json'
    origin_path.write_text(json.dumps(origin))
    item['producer'] = dict(path=str(origin_path), **file_pin(origin_path))
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match=expected):
        execute(load_spec(path))
    assert not (tmp_path/'work').exists() and not (tmp_path/'catalog').exists()


def test_import_spec_requires_a_location_matching_its_catalog(tmp_path):
    from viewer_publication.archive_import_job import load_spec
    source=tmp_path/'rows.parquet';pq.write_table(ROWS,source)
    with pytest.raises(ValueError,match='local location'):
        load_spec(_spec(tmp_path,source,location='s3://bucket/prefix'))
    with pytest.raises(ValueError,match='s3 location'):
        load_spec(_spec(tmp_path,source,catalog_root=None))


def test_import_adopts_an_empty_table_and_refuses_one_with_rows(tmp_path,monkeypatch):
    import congress_api.retention.writer_identity as identity
    from viewer_publication.archive_import_job import execute,load_spec
    from congress_api.lake.tables import create_table
    from docspec_client.client import NativeDatasets
    monkeypatch.setattr(identity,'writer_identity',lambda root,job:dict(job=job,commit='c'*40,lockfile_digest='d'*64))
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
    path=_spec(tmp_path,source);value=json.loads(path.read_text())
    item=value['tables']['meeting_records']
    origin=tmp_path/'origin.json';origin.write_text(json.dumps(dict(version=1,input='meeting_records',job='daily',commit='e'*40,
        selector=dict(kind='parquet',**item['source']))))
    item['producer']=dict(path=str(origin),**file_pin(origin));path.write_text(json.dumps(value))
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
        origin.write_text(json.dumps(dict(version=1,input=name,job='archive_backfill_job.py',commit='e'*40,
            selector=dict(kind='parquet',**meeting['source']))))
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


def _init_git_repo(repo, *jobs):
    import subprocess
    repo.mkdir()
    (repo / 'uv.lock').write_text('version = 1\n')
    for job in jobs:
        job_file = repo / job
        job_file.parent.mkdir(parents=True, exist_ok=True)
        job_file.write_text(f'# {job}\n')
    env = {
        **os.environ,
        'GIT_AUTHOR_NAME': 'Test',
        'GIT_AUTHOR_EMAIL': 'test@example.com',
        'GIT_COMMITTER_NAME': 'Test',
        'GIT_COMMITTER_EMAIL': 'test@example.com',
    }
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True, env=env)
    subprocess.run(['git', '-C', str(repo), 'add', 'uv.lock', *jobs], check=True, env=env)
    subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'init'], check=True, env=env)
    head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    return head, env


def test_import_refuses_dirty_tree_or_unreachable_origin_before_creating_table_and_rechecks_after_write(tmp_path, monkeypatch):
    """ct-h267: writer_identity runs before target lookup/create and again after the write."""
    import subprocess
    import viewer_publication.producer_proof as proof
    from viewer_publication.archive_import_job import IMPORT_JOB, execute, load_spec

    repo = tmp_path / 'repo'
    head, env = _init_git_repo(repo, IMPORT_JOB, proof.DAILY)
    monkeypatch.setattr(proof, 'ROOT', repo)

    source = tmp_path / 'rows.parquet'
    pq.write_table(ROWS, source)
    (tmp_path / 'dirty-case').mkdir(parents=True, exist_ok=True)
    path = _spec(tmp_path / 'dirty-case', source)
    dirty_file = repo / 'untracked.txt'
    dirty_file.write_text('dirty\n')

    # Dirty checkout fails fast before opening catalog or creating work/tables.
    with pytest.raises(ValueError, match='clean application tree'):
        execute(load_spec(path))
    assert not (tmp_path / 'dirty-case/work').exists()
    assert not (tmp_path / 'dirty-case/catalog').exists()
    dirty_file.unlink()

    # Chained import or unregistered/missing origin job at commit refuses before creating work/tables.
    for case_name, bad_job, pattern in [
        ('chained-import', IMPORT_JOB, 'cannot name another import'),
        ('missing-at-commit', proof.BACKFILL, 'not checked in'),
    ]:
        bad_dir = tmp_path / case_name
        bad_dir.mkdir()
        b_path = _spec(bad_dir, source)
        b_val = json.loads(b_path.read_text())
        bad_origin = bad_dir / 'origin.json'
        bad_origin.write_text(json.dumps(dict(
            version=1, input='meeting_records', job=bad_job, commit=head,
            selector=dict(kind='parquet', **b_val['tables']['meeting_records']['source']),
        )))
        b_val['tables']['meeting_records']['producer'] = dict(path=str(bad_origin), **file_pin(bad_origin))
        b_path.write_text(json.dumps(b_val))
        with pytest.raises(ValueError, match=pattern):
            execute(load_spec(b_path))
        assert not (bad_dir / 'work').exists()
        assert not (bad_dir / 'catalog').exists()

    # Unreachable origin commit on a clean checkout also refuses before creating work/tables.
    unreachable_dir = tmp_path / 'unreachable-case'
    unreachable_dir.mkdir()
    u_path = _spec(unreachable_dir, source)
    u_val = json.loads(u_path.read_text())
    subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '--orphan', 'side'], check=True, env=env)
    (repo / 'side.txt').write_text('side\n')
    subprocess.run(['git', '-C', str(repo), 'add', 'side.txt'], check=True, env=env)
    subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'side'], check=True, env=env)
    side_commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(repo), 'checkout', '-q', head], check=True, env=env)
    (repo / 'side.txt').unlink(missing_ok=True)
    origin = unreachable_dir / 'origin.json'
    origin.write_text(json.dumps(dict(
        version=1, input='meeting_records', job=proof.DAILY, commit=side_commit,
        selector=dict(kind='parquet', **u_val['tables']['meeting_records']['source']),
    )))
    u_val['tables']['meeting_records']['producer'] = dict(path=str(origin), **file_pin(origin))
    u_path.write_text(json.dumps(u_val))
    with pytest.raises(ValueError, match='not reachable from HEAD'):
        execute(load_spec(u_path))
    assert not (unreachable_dir / 'work').exists()
    assert not (unreachable_dir / 'catalog').exists()

    # Tree dirtied mid-write is caught by the post-write writer_identity check and writes no producer record.
    mid_dir = tmp_path / 'mid-dirty'
    mid_dir.mkdir()
    m_path = _spec(mid_dir, source)
    m_val = json.loads(m_path.read_text())
    good_origin = mid_dir / 'origin.json'
    good_origin.write_text(json.dumps(dict(
        version=1, input='meeting_records', job=proof.DAILY, commit=head,
        selector=dict(kind='parquet', **m_val['tables']['meeting_records']['source']),
    )))
    m_val['tables']['meeting_records']['producer'] = dict(path=str(good_origin), **file_pin(good_origin))
    m_path.write_text(json.dumps(m_val))
    import congress_api.lake.maintenance as maintenance
    real_verify = maintenance.verify_generations

    def dirty_during_verify(*args, **kwargs):
        out = real_verify(*args, **kwargs)
        (repo / 'appeared-during-write.txt').write_text('dirty\n')
        return out

    monkeypatch.setattr(maintenance, 'verify_generations', dirty_during_verify)
    with pytest.raises(ValueError, match='clean application tree|writer identity changed'):
        execute(load_spec(m_path))
    assert not (mid_dir / 'work/producers').exists()

