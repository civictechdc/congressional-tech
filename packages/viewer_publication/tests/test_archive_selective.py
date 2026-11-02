"""Selective backfill on real producers. Expectations come from injected facts, not this code."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import selective_base,selective_spec
from congress_api.lake import appearance_records,captures,meeting_records
from congress_api.lake.capture_backfill_guard import GenerationViolation
from congress_api.lake.filenames import current_version as catalog_version
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_backfill_job import execute
from viewer_publication.archive_selective_records import SelectiveStop

B="receipt_key LIKE '%/b.jsonl.gz' AND receipt_line=1"
BOTH="receipt_key LIKE '%/b%.jsonl.gz'"
PK={'captures':list(captures.PK),'readings':['body_sha','parser','parser_version'],'filename_readings':['filename','source_url','catalog_version'],
    'meeting_records':['record_sha','source','parser_version'],'appearance_records':['record_sha','source','parser_version']}


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    return selective_base(tmp_path_factory.mktemp('selective-base'))


def changed(tmp_path,fixture,name,update):
    """A base table with `update(rows)` applied, written beside the test."""
    table=pq.read_table(fixture['base'][name]);rows=table.to_pylist();update(rows)
    path=tmp_path/('stale-'+name+'.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),path)
    return str(path)


def on_receipt(rows,suffix):
    return [row for row in rows if row['receipt_key'].endswith(suffix)]


def head(spec,name):
    """The final table's rows, read through the catalog."""
    state=json.loads((Path(spec['work'])/'state.json').read_text());work=Path(spec['work'])/('read-'+name+os.urandom(4).hex())
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        run_job(work,engine,inputs=[dict(name='t',kind='native_table',**state['pins'][name])],steps=[],
            outputs=[parquet_output(work,'rows','SELECT * FROM t',PK[name])])
    return pq.read_table(work/'rows.parquet').to_pylist()


def sorted_rows(rows):
    return sorted(rows,key=lambda row:repr(sorted(row.items(),key=lambda item:item[0])))


@pytest.mark.parametrize('change,message',[
    (dict(catalog_root=None),'local catalog_root'),
    (dict(tables={name:dict(namespace=['archive'],name=name) for name in ('captures','readings','filename_readings','meeting_records','appearance_records')}),'archive namespace'),
])
def test_refuses_unsafe_targets_before_any_effect(tmp_path,fixture,change,message):
    with pytest.raises(ValueError,match=message):
        selective_spec(tmp_path,fixture,dict(captures=B),**change)
    assert not (tmp_path/'work').exists() and not (tmp_path/'catalog').exists()


@pytest.mark.parametrize('where,message',[
    (dict(readings='true'),'ct-pocg'),(dict(),'at least one predicate'),(dict(captures='true; DROP'),'semicolon'),
])
def test_refuses_bad_predicates_before_any_effect(tmp_path,fixture,where,message):
    with pytest.raises(ValueError,match=message):selective_spec(tmp_path,fixture,where)
    assert not (tmp_path/'work').exists()


def test_refuses_a_digest_mismatch_and_absent_raw_root_before_any_effect(tmp_path,fixture):
    spec=selective_spec(tmp_path/'digest',fixture,dict(captures=B))
    spec['selective']['base']['captures']['sha256']='0'*64
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not Path(spec['work']).exists()
    moved=dict(fixture,raw=tmp_path/'absent')
    with pytest.raises(ValueError,match='raw_root is absent'):selective_spec(tmp_path/'raw',moved,dict(captures=B))


def test_zero_hits_stops_before_any_table_exists(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures="receipt_key='absent'"))
    with pytest.raises(SelectiveStop,match='selects no rows'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_restamping_without_a_differential_is_refused(tmp_path,fixture):
    def stale(rows):rows[0]['parser_version']='old'
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(meeting_records=changed(tmp_path,fixture,'meeting_records',stale)))
    with pytest.raises(SelectiveStop,match='re-stamped with no differential'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_narrow_fix_rebuilds_the_whole_receipt_and_reuses_the_rest_untouched(tmp_path,fixture):
    def stale(rows):
        on_receipt(rows,'/b.jsonl.gz')[0]['http_status']=299
        on_receipt(rows,'/a.jsonl.gz')[0]['http_status']=201
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(captures=changed(tmp_path,fixture,'captures',stale)))
    report=execute(spec)
    assert report['status']=='built'
    rows=head(spec,'captures')
    assert [row['http_status'] for row in on_receipt(rows,'/b.jsonl.gz')]==[200,200]
    assert {row['http_status'] for row in on_receipt(rows,'/a.jsonl.gz')}=={200,201}
    assert len(rows)==sum(row['expected_captures'] for row in fixture['counts'])
    # One predicate hit expanded to its whole receipt; the guard cannot see this difference.
    assert report['tables']['captures']['hits']==1 and report['tables']['captures']['selected']==2
    assert report['rebuilt_diff']=={'http_status':1}
    assert (Path(spec['work'])/'candidate-model.json').is_file() and (Path(spec['work'])/'candidate-publish.json').is_file()


def test_null_predicate_rows_are_seeded_not_dropped(tmp_path,fixture):
    # True for one row and NULL for every other: a bare NOT would drop them all.
    spec=selective_spec(tmp_path,fixture,dict(filename_readings="CASE WHEN filename LIKE 'b-one%' THEN true END"),differential_rows=0)
    report=execute(spec)
    base=pq.ParquetFile(fixture['base']['filename_readings']).metadata.num_rows
    assert base>1 and report['tables']['filename_readings']['selected']==1
    assert len(head(spec,'filename_readings'))==base


def test_selected_records_recompute_and_unselected_are_restamped_identically(tmp_path,fixture):
    meeting=meeting_records.current_versions()
    def stale_meeting(rows):
        for row in rows:row['parser_version']='old-meeting'
    def stale_appearance(rows):
        for row in rows:row['parser_version']='old-appearance'
    def stale_names(rows):
        for row in rows:row['catalog_version']='old-catalog'
    base=dict(meeting_records=changed(tmp_path,fixture,'meeting_records',stale_meeting),
        appearance_records=changed(tmp_path,fixture,'appearance_records',stale_appearance),
        filename_readings=changed(tmp_path,fixture,'filename_readings',stale_names))
    spec=selective_spec(tmp_path,fixture,dict(meeting_records="source='house_xml'",appearance_records="source='congress_gov'",filename_readings="filename LIKE 'b-one%'"),base=base)
    report=execute(spec)
    assert report['tables']['meeting_records']['appended']==report['tables']['meeting_records']['selected']>0
    assert report['tables']['appearance_records']['restamped']>0
    rows=head(spec,'meeting_records')
    assert {row['parser_version'] for row in rows}<=set(meeting.values())
    assert {row['catalog_version'] for row in head(spec,'filename_readings')}=={catalog_version()}
    def without(rows,column):return sorted_rows([{k:v for k,v in row.items() if k!=column} for row in rows])
    for name,column in (('meeting_records','parser_version'),('appearance_records','parser_version'),('filename_readings','catalog_version')):
        assert without(head(spec,name),column)==without(pq.read_table(fixture['base'][name]).to_pylist(),column)
    assert report['differential']['meeting_records'] and report['differential']['filename_readings']


def test_too_narrow_predicate_stops_naming_the_key_and_column(tmp_path,fixture):
    def sentinel(rows):on_receipt(rows,'/c.jsonl.gz')[0]['http_status']=201
    spec=selective_spec(tmp_path,fixture,dict(captures=B),base=dict(captures=changed(tmp_path,fixture,'captures',sentinel)))
    with pytest.raises(SelectiveStop,match=r'c\.jsonl\.gz.*differs in http_status'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_differential_stops_when_a_table_had_nothing_to_check(tmp_path,fixture):
    spec=selective_spec(tmp_path,dict(fixture,inventory=[row for row in fixture['inventory'] if row['key'].endswith('/b.jsonl.gz')]),dict(captures=B))
    with pytest.raises(SelectiveStop,match='no unselected receipt'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_rows_recomputed_but_absent_from_base_also_stop(tmp_path,fixture):
    def lost(rows):rows.remove(on_receipt(rows,'/m.jsonl.gz')[0])
    spec=selective_spec(tmp_path,fixture,dict(captures=B),base=dict(captures=changed(tmp_path,fixture,'captures',lost)))
    with pytest.raises(SelectiveStop,match='recomputed but not in base'):execute(spec)


def test_wrong_independent_count_fails_closed(tmp_path,fixture):
    counts=[dict(row,expected_captures=row['expected_captures']+1,list_items=row['list_items']+1) if row['key'].endswith('/b.jsonl.gz') else row for row in fixture['counts']]
    spec=selective_spec(tmp_path,fixture,dict(captures=B),counts=counts,differential_rows=0)
    with pytest.raises(RuntimeError,match='Batch exited'):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_filename_only_run_guards_with_a_wrong_count(tmp_path,fixture):
    counts=[dict(row,expected_captures=9,list_items=9) if row['key'].endswith('/a.jsonl.gz') else row for row in fixture['counts']]
    spec=selective_spec(tmp_path,fixture,dict(filename_readings="filename LIKE 'b-one%'"),counts=counts,differential_rows=0)
    with pytest.raises(GenerationViolation):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_positive_model_invariant_leaves_no_candidates(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as module
    def lost(*args,**kwargs):raise ValueError('Release key invariant failed')
    monkeypatch.setattr(module,'execute_model',lost)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    with pytest.raises(ValueError,match='invariant'):execute(spec)
    assert not (Path(spec['work'])/'candidate-model.json').exists()


def test_absent_suite_leaves_no_candidates(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as module
    monkeypatch.setattr(module,'SUITES',(*module.SUITES,'suite_that_never_ran'))
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    with pytest.raises(SelectiveStop,match='suite_that_never_ran'):execute(spec)
    assert not (Path(spec['work'])/'candidate-publish.json').exists()


def test_missing_selected_body_lists_every_gap_before_any_append(tmp_path,fixture):
    mirror=tmp_path/'mirror';shutil.copytree(fixture['raw'],mirror)
    table=pq.read_table(fixture['base']['meeting_records']).to_pylist()
    shas=[row['record_sha'].hex() for row in table if row['source']=='house_xml']
    assert shas
    for sha in shas:(mirror/'bodies/sha256'/sha[:2]/(sha+'.gz')).unlink()
    moved=dict(fixture,raw=mirror,inventory=[dict(row,path=row['path'].replace(str(fixture['raw']),str(mirror))) for row in fixture['inventory']])
    spec=selective_spec(tmp_path,moved,dict(meeting_records="source='house_xml'"),differential_rows=0)
    with pytest.raises(SelectiveStop,match='not available') as error:execute(spec)
    assert all(sha in str(error.value) for sha in shas)
    assert 'd4' not in json.loads((Path(spec['work'])/'state.json').read_text()) or not json.loads((Path(spec['work'])/'state.json').read_text())['d4']


def test_selected_receipt_absent_from_inventory_is_a_named_gap(tmp_path,fixture):
    spec=selective_spec(tmp_path,dict(fixture,inventory=[row for row in fixture['inventory'] if not row['key'].endswith('/b.jsonl.gz')]),dict(captures=B),differential_rows=0)
    with pytest.raises(SelectiveStop,match=r'absent from the inventory.*b\.jsonl\.gz'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_gpo_mods_digest_mismatch_refuses(tmp_path,fixture):
    from viewer_publication.archive_selective_records import Bodies
    xml=tmp_path/'mods';xml.mkdir();(xml/'CHRG-1.xml').write_bytes(b'<mods/>')
    receipts=tmp_path/'receipts.jsonl';receipts.write_text(json.dumps(dict(package_id='CHRG-1',sha256='0'*64))+'\n')
    class Run:
        selective=dict(raw_root=str(fixture['raw']),body_fallback=dict(gpo_mods=dict(receipts=str(receipts),root=str(xml))))
        attempt=tmp_path/'attempt'
    with pytest.raises(ValueError,match='digest mismatch'):Bodies(Run()).selection('appearance_records',[dict(record_sha='0'*64,source='mods')])


def test_resume_refuses_changed_identity_and_needs_resume_flag(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,decided_at=None)
    execute(spec)
    with pytest.raises(ValueError,match='set resume'):execute(spec)
    # An omitted decided_at is fixed by the first run, so resuming later still matches.
    finished=execute(dict(spec,resume=True));assert finished['status']=='built'
    changed_where=dict(spec,resume=True,selective=dict(spec['selective'],where=dict(captures=BOTH)))
    with pytest.raises(ValueError,match='identity changed'):execute(changed_where)
    with pytest.raises(ValueError,match='resume found no state'):execute(dict(spec,work=str(tmp_path/'none'),resume=True))


RESUME_SCRIPT='''
import json,os,signal,sys
from pathlib import Path
from congress_api.lake import capture_backfill,meeting_records
import viewer_publication.archive_selective as selective
from viewer_publication.archive_backfill_job import execute,load_spec
spec=load_spec(sys.argv[1]);boundary=sys.argv[2]
actual=capture_backfill.execute_batches
capture_backfill.execute_batches=lambda *a,**k:actual(*a,**dict(k,item_target=1))
def die():os.kill(os.getpid(),signal.SIGKILL)
def after(module,name):
    original=getattr(module,name)
    def wrapped(*a,**k):
        result=original(*a,**k);die();return result
    setattr(module,name,wrapped)
if boundary=='seed':after(selective,'_seed')
elif boundary=='d1_first_batch':
    original=capture_backfill.monitor_command
    def first(*a,**k):
        result=original(*a,**k);die();return result
    capture_backfill.monitor_command=first
elif boundary=='daily':after(selective,'_daily')
elif boundary=='d4_meeting':after(meeting_records,'append')
elif boundary=='guard':after(selective,'_guard')
execute(spec)
'''


@pytest.fixture(scope='module')
def uninterrupted(fixture,tmp_path_factory):
    spec=selective_spec(tmp_path_factory.mktemp('selective-whole'),fixture,dict(captures=BOTH,meeting_records="source='house_xml'"),differential_rows=0)
    execute(spec)
    return {name:sorted_rows(head(spec,name)) for name in PK}


@pytest.mark.parametrize('boundary',['seed','d1_first_batch','daily','d4_meeting','guard'])
def test_fresh_process_resume_matches_an_uninterrupted_run(tmp_path,fixture,uninterrupted,boundary):
    mirror=tmp_path/'mirror';shutil.copytree(fixture['raw'],mirror)
    moved=dict(fixture,raw=mirror,inventory=[dict(row,path=row['path'].replace(str(fixture['raw']),str(mirror))) for row in fixture['inventory']])
    for row in moved['inventory']:
        pin=json.loads(Path(row['qualification']).read_text());copy=tmp_path/Path(row['qualification']).name
        copy.write_text(json.dumps(dict(pin,path=row['path'])));row['qualification']=str(copy)
    spec=selective_spec(tmp_path,moved,dict(captures=BOTH,meeting_records="source='house_xml'"),differential_rows=0)
    script=tmp_path/'kill.py';script.write_text(RESUME_SCRIPT);path=tmp_path/'spec.json'
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).parent)+os.pathsep+os.environ.get('PYTHONPATH',''))
    assert subprocess.run([sys.executable,str(script),str(path),boundary],env=env).returncode==-9
    if boundary=='d1_first_batch':
        [batch]=list(Path(spec['work']).glob('attempts/*/d1/batch-0000-*'))
        for row in json.loads((batch/'receipts.json').read_text()):Path(row['path']).unlink()
    value=json.loads(path.read_text());value['resume']=True;path.write_text(json.dumps(value))
    assert subprocess.run([sys.executable,str(script),str(path),'none'],env=env).returncode==0
    final={name:sorted_rows(head(spec,name)) for name in PK}
    assert final==uninterrupted
    for name,keys in PK.items():
        seen=[tuple(row[k] for k in keys) for row in final[name]]
        assert len(seen)==len(set(seen))
    assert (Path(spec['work'])/'candidate-model.json').is_file()


def test_candidate_goes_through_the_controller_and_resumes_after_canary_failure(tmp_path,fixture):
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    import viewer_publication.archive_controller as controller
    from viewer_publication.archive_model_job import load_spec
    from viewer_publication.archive_publish_job import load_spec as load_publish
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    execute(spec)
    candidate=Path(spec['work'])/'candidate-model.json'
    publish=json.loads((Path(spec['work'])/'candidate-publish.json').read_text())
    assert 'daily' not in publish and publish['model_spec']['path']==str(candidate)
    assert load_publish(Path(spec['work'])/'candidate-publish.json')['_model']['captures']['kind']=='native_table'
    store=Store();built=[]
    def passed(**ctx):return dict(status='passed',releaseId=ctx['release_id'],targets='owner-approved')
    def failed(**ctx):raise RuntimeError('injected canary failure')
    original=controller.build_prepared_release
    def counted(*a,**k):
        built.append(1);return original(*a,**k)
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        kwargs=dict(first_release=True,client=store,engine=Runtime(native,store),bucket='derived-fixture',work=tmp_path/'publish',receipt_keys=publish['receipt_keys'],
            provenance=[],run={'id':'selective'},public_origin='https://archive.fixture.test',contract=passed)
        patch=pytest.MonkeyPatch();patch.setattr(controller,'build_prepared_release',counted)
        try:
            with pytest.raises(RuntimeError,match='injected canary'):controller.run_publish(load_spec(candidate),canary=failed,**kwargs)
            assert controller.run_publish(load_spec(candidate),canary=passed,resume=True,**kwargs)['status']=='published'
        finally:patch.undo()
    assert len(built)==1
