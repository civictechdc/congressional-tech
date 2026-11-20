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
from congress_api.lake import appearance_records,captures,committee_records,meeting_records,video_records
from congress_api.lake.capture_backfill_guard import GenerationViolation
from congress_api.lake.filenames import current_version as catalog_version
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets
from native_test_helpers import compatible_entry
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
            outputs=[parquet_output(work,'rows','SELECT * FROM t',PK.get(name,['record_sha','source','parser_version']))])
    return pq.read_table(work/'rows.parquet').to_pylist()


def sorted_rows(rows):
    return sorted(rows,key=lambda row:repr(sorted(row.items(),key=lambda item:item[0])))


def test_resume_refuses_changed_identity_and_needs_resume_flag(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,decided_at=None)
    execute(spec)
    with pytest.raises(ValueError,match='set resume'):execute(spec)
    # An omitted decided_at is fixed by the first run, so resuming later still matches.
    finished=execute(dict(spec,resume=True));assert finished['status']=='built'
    changed_where=dict(spec,resume=True,selective=dict(spec['selective'],where=dict(captures=BOTH)))
    with pytest.raises(ValueError,match='identity changed'):execute(changed_where)
    with pytest.raises(ValueError,match='resume found no state'):execute(dict(spec,work=str(tmp_path/'none'),resume=True))


def test_a_model_runtime_change_resumes_and_a_predicate_change_still_refuses(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables')
    assert execute(spec)['status']=='tables_built'
    # Defect guarded: identity covering the model runtime, so a retry with a new pool redoes D1-D4.
    from archive_job_fixture import runtime_ran
    from docspec_client.client import runtime_paths
    original=Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve()
    # Preserve each path's meaning when the retry config moves to another directory.
    runtime=runtime_paths(json.loads(original.read_text()),original.parent)
    other=tmp_path/'model-runtime.json';other.write_text(json.dumps(runtime))
    retry=dict(spec,resume=True,through='model',selective=dict(spec['selective'],model=dict(spec['selective']['model'],engine_config=str(other))))
    assert execute(retry)['status']=='built'
    # The state keeps the record of the runtime the model ran under: the retry's (ct-64t4).
    assert json.loads((Path(spec['work'])/'state.json').read_text())['model']['runtime']==runtime_ran(other)
    with pytest.raises(ValueError,match='identity changed'):
        execute(dict(spec,resume=True,selective=dict(spec['selective'],where=dict(captures=BOTH))))


def test_an_unaccepted_model_attempt_is_cleared_before_the_retry(tmp_path,fixture):
    # Defect guarded: a failed attempt's scratch left behind, so the next check_scratch refuses.
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables')
    execute(spec)
    junk=Path(spec['work'])/'model-scratch'/'junk';junk.parent.mkdir();junk.write_bytes(b'x')
    assert execute(dict(spec,resume=True,through='model'))['status']=='built'
    assert not junk.exists()


def test_tables_then_model_matches_an_uninterrupted_run(tmp_path,fixture,uninterrupted):
    spec=selective_spec(tmp_path,fixture,dict(captures=BOTH,meeting_records="source='house_xml'"),differential_rows=0,through='tables')
    execute(spec);assert (Path(spec['work'])/'tables-report.json').is_file()
    execute(dict(spec,resume=True,through='model'))
    assert {name:sorted_rows(head(spec,name)) for name in PK}==uninterrupted


def test_scratch_checks_refuse_before_any_table(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as selective
    from congress_api.lake import capture_backfill
    spec=selective_spec(tmp_path/'owned',fixture,dict(captures=B),differential_rows=0)
    monkeypatch.setattr(selective,'SCRATCH_BYTES',1)
    with pytest.raises(RuntimeError):execute(spec)
    assert not Path(spec['catalog_root']).exists()
    monkeypatch.undo()
    spec=selective_spec(tmp_path/'disk',fixture,dict(captures=B),differential_rows=0)
    usage=capture_backfill.shutil.disk_usage
    monkeypatch.setattr(capture_backfill.shutil,'disk_usage',lambda path:usage(path)._replace(free=1<<30))
    with pytest.raises(RuntimeError,match='Free disk'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


@pytest.mark.parametrize('defect',['drop','wrong_version'])
def test_the_d4_reconcile_sees_a_lost_or_mislabelled_row(tmp_path,fixture,monkeypatch,defect):
    # Defect guarded: deleting the reconcile query lets a lost or mis-versioned row pass.
    original=meeting_records.append
    def append(staged,**kwargs):
        table=pq.read_table(staged['records']);rows=table.to_pylist()
        rows=rows[1:] if defect=='drop' else [dict(rows[0],parser_version='wrong'),*rows[1:]]
        path=Path(str(staged['records'])+'.altered.parquet');pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),path)
        return original(dict(staged,records=path),**kwargs)
    monkeypatch.setattr(meeting_records,'append',append)
    spec=selective_spec(tmp_path,fixture,dict(meeting_records="source='house_xml'"),differential_rows=0,through='tables')
    with pytest.raises(SelectiveStop,match='a row was lost'):execute(spec)


def test_completion_appends_a_candidate_the_base_never_had_and_stops_over_budget(tmp_path,fixture):
    base=pq.read_table(fixture['base']['meeting_records']).to_pylist()
    house=[row for row in base if row['source']=='house_xml']
    assert house
    def missing(rows):rows[:]=[row for row in rows if row['record_sha']!=house[0]['record_sha'] or row['source']!='house_xml']
    stale=dict(meeting_records=changed(tmp_path,fixture,'meeting_records',missing))
    spec=selective_spec(tmp_path/'ok',fixture,dict(captures=B),differential_rows=0,base=stale,through='tables')
    report=execute(spec)
    assert report['completion']['meeting_records']=={'appended':1,'sources':{'house_xml':1}}
    assert report['tables']['meeting_records']['appended']==1
    assert sorted_rows(head(spec,'meeting_records'))==sorted_rows(base)
    # Every meeting missing: more completion work than a budget of one.
    (tmp_path/'over').mkdir()
    none=dict(meeting_records=changed(tmp_path/'over',fixture,'meeting_records',lambda rows:rows.clear()))
    over=selective_spec(tmp_path/'over',fixture,dict(captures=B),differential_rows=0,base=none,through='tables',batch_size=1,max_batches=1)
    with pytest.raises(SelectiveStop,match=f'{len(base)} work items, over max_work_items 1'):execute(over)


def test_a_failed_model_attempt_is_cleared_before_the_first_scratch_check(tmp_path,fixture,monkeypatch):
    # Defect guarded: cleaning model-scratch only after a scratch check has already counted it.
    import viewer_publication.archive_selective as selective
    from congress_api.lake.capture_backfill import _allocated_bytes
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables')
    execute(spec)
    junk=Path(spec['work'])/'model-scratch'/'junk';junk.parent.mkdir();junk.write_bytes(os.urandom(8<<20))
    monkeypatch.setattr(selective,'SCRATCH_BYTES',_allocated_bytes(Path(spec['work']))-(4<<20))
    assert execute(dict(spec,resume=True,through='model'))['status']=='built'


def test_the_model_checks_scratch_after_the_tables_are_built(tmp_path,fixture,monkeypatch):
    # Defect guarded: deleting _model's check, so tables that grew the work go unchecked.
    import viewer_publication.archive_selective as selective
    events=[]
    for name in ('_guard','execute_model'):
        original=getattr(selective,name)
        def wrapped(*a,_original=original,_name=name,**k):
            result=_original(*a,**k);events.append(_name);return result
        monkeypatch.setattr(selective,name,wrapped)
    check=selective.Run.check_scratch
    monkeypatch.setattr(selective.Run,'check_scratch',lambda self:(events.append('check'),check(self))[1])
    execute(selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0))
    assert 'check' in events[events.index('_guard'):events.index('execute_model')]


def test_the_reconcile_keys_rows_by_source(tmp_path,fixture,monkeypatch):
    # Defect guarded: reconciling on record_sha alone counts a same-body row of another source.
    from viewer_publication.archive_selective import _versions
    base=pq.read_table(fixture['base']['meeting_records']);rows=base.to_pylist()
    lost=next(row for row in rows if row['source']=='house_xml')
    twin=dict(lost,source='congress_gov',parser_version=_versions()['meeting_records']['congress_gov'])
    path=tmp_path/'twin-meetings.parquet';pq.write_table(pa.Table.from_pylist([*rows,twin],schema=base.schema),path)
    original=meeting_records.append
    def append(staged,**kwargs):
        table=pq.read_table(staged['records']);kept=[r for r in table.to_pylist() if r['record_sha']!=lost['record_sha']]
        out=Path(str(staged['records'])+'.dropped.parquet');pq.write_table(pa.Table.from_pylist(kept,schema=table.schema),out)
        return original(dict(staged,records=out),**kwargs)
    monkeypatch.setattr(meeting_records,'append',append)
    spec=selective_spec(tmp_path,fixture,dict(meeting_records="source='house_xml'"),differential_rows=0,base=dict(meeting_records=str(path)),through='tables')
    with pytest.raises(SelectiveStop,match='a row was lost'):execute(spec)


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


def test_step_9_model_build_passes_base_retired_ledger_matching_publisher(tmp_path,fixture,monkeypatch):
    """ct-wzyo: when selective.model names ledger_base (or ledger), step 9 passes the retired-link ledger
    the publisher derives from the base release, producing identical retired_links rows and release_id;
    when neither is named, run.state['model']['ledger'] states explicitly that the build used an empty ledger."""
    from hashlib import md5,sha256
    from archive_job_fixture import fake_release
    from test_archive_controller import Runtime
    from test_archive_publish import Store
    import viewer_publication.archive_controller as controller
    import viewer_publication.archive_publish as archive_publish
    from viewer_publication.archive_backfill_job import load_spec as load_backfill
    from viewer_publication.archive_format import release_identity
    from viewer_publication.archive_model_job import load_spec

    # 1. Invalid ledger options refuse at load_spec before any effect.
    spec_dir=tmp_path/'bad'
    selective_spec(spec_dir,fixture,dict(captures=B),differential_rows=0)
    raw_spec=json.loads((spec_dir/'spec.json').read_text())
    bare_base=fake_release(tmp_path/'bare','a'*64,[('gone.pdf',b'gggggggg',[b'gggggggg'])],retired=None)
    for bad,msg in [
        (dict(ledger=str(tmp_path/'missing-ready')),'Ledger folder lacks prior_links.parquet'),
        (dict(ledger_base=str(bare_base)),'has no retired_links'),
        (dict(ledger=str(tmp_path/'r'),ledger_base=str(bare_base)),'ledger or ledger_base, not both'),
    ]:
        edited=dict(raw_spec,selective=dict(raw_spec['selective'],model=dict(raw_spec['selective']['model'],**bad)))
        p=tmp_path/'bad-spec.json';p.write_text(json.dumps(edited))
        with pytest.raises(ValueError,match=msg):load_backfill(p)
        assert not (spec_dir/'work').exists()

    # 2. Without ledger or ledger_base, state and report say explicitly that the ledger was empty.
    empty_spec=selective_spec(tmp_path/'empty',fixture,dict(captures=B),differential_rows=0)
    empty_report=execute(empty_spec)
    empty_state=json.loads((Path(empty_spec['work'])/'state.json').read_text())
    assert empty_state['model']['ledger']['empty'] is True
    assert 'empty retired-link ledger' in empty_state['model']['ledger']['reason']
    assert empty_report['ledger']==empty_state['model']['ledger']

    # 3. With a base release carrying retired_links, step 9's retired_links rows and release_id equal the publisher's.
    base_dir=fake_release(tmp_path/'base','0'*64,[('gone.pdf',b'gggggggg',[b'gggggggg'])],
        retired=[dict(link_key=b'rrrrrrrr',successor_key=None,last_release_id='d'*64,last_filename='r.pdf')])
    entries=[]
    for f in sorted(base_dir.glob('*.parquet')):
        data=f.read_bytes()
        entries.append(dict(name=f.name,sha256=sha256(data).hexdigest(),md5=md5(data).hexdigest(),
            size=len(data),rows=pq.read_metadata(f).num_rows))
    base_id=release_identity(1,entries)
    (base_dir/'manifest.json').write_text(json.dumps(dict(schema_version=1,files=entries,facet_counts=[],release_id=base_id)))

    seeded_dir=tmp_path/'seeded'
    selective_spec(seeded_dir,fixture,dict(captures=B),differential_rows=0)
    seeded_json=json.loads((seeded_dir/'spec.json').read_text())
    seeded_json['selective']['model']['ledger_base']=str(base_dir)
    (seeded_dir/'spec.json').write_text(json.dumps(seeded_json))
    spec=load_backfill(seeded_dir/'spec.json')
    report=execute(spec)

    store=Store()
    for f in base_dir.iterdir():
        store.objects[f'viewer-publications/releases/{base_id}/{f.name}']=f.read_bytes()
    store.objects['viewer-publications/manifest.json']=json.dumps(dict(release_id=base_id,previous_release_id=None)).encode()
    monkeypatch.setattr(archive_publish,'require_release_gates',lambda *a,**k:None)
    candidate=Path(spec['work'])/'candidate-model.json'
    publish=json.loads((Path(spec['work'])/'candidate-publish.json').read_text())
    def passed(**ctx):return dict(status='passed',releaseId=ctx['release_id'],targets='owner-approved')
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as native:
        pub_result=controller.run_publish(load_spec(candidate),canary=passed,contract=passed,
            client=store,engine=Runtime(native,store),bucket='derived-fixture',work=tmp_path/'publish',
            receipt_keys=publish['receipt_keys'],provenance=[],run={'id':'selective'},
            public_origin='https://archive.fixture.test')
    assert pub_result['status']=='published'
    step9_retired=pq.read_table(Path(report['release'])/'retired_links.parquet').to_pylist()
    pub_retired=pq.read_table(Path(spec['work'])/'candidate-output'/'retired_links.parquet').to_pylist()
    assert step9_retired==pub_retired
    assert {r['link_key'] for r in step9_retired}=={b'gggggggg',b'rrrrrrrr'}
    assert report['release_id']==pub_result['release_id']
    assert report['ledger']['source']=='ledger_base'

    # 4. Resuming a completed empty-ledger run after adding ledger_base invalidates step 9 and rebuilds it.
    empty_json=json.loads((tmp_path/'empty'/'spec.json').read_text())
    empty_json['resume']=True
    empty_json['selective']['model']['ledger_base']=str(base_dir)
    (tmp_path/'empty'/'spec.json').write_text(json.dumps(empty_json))
    resumed=execute(load_backfill(tmp_path/'empty'/'spec.json'))
    assert resumed['executed'] is True
    assert resumed['ledger']['source']=='ledger_base'
    assert resumed['release_id']==pub_result['release_id']


def test_the_selective_job_records_the_producer_of_every_snapshot_it_pins(tmp_path,fixture,monkeypatch):
    """Gate 5 refused spec-run's D1-D4 candidate: nothing wrote a producer record. The job that
    made the snapshots now writes them, named honestly, and pins them in candidate-publish.json."""
    import subprocess as sp
    import viewer_publication.archive_selective as selective
    from viewer_publication.producer_proof import snapshot_reasons
    head_commit=sp.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    # The test tree may be dirty; the identity is the checked-in HEAD, as writer_identity names it on a clean tree.
    monkeypatch.setattr(selective,'_writer',lambda run:dict(job=selective.PRODUCER_JOB,commit=head_commit,lockfile_digest='0'*64))
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    report=execute(spec)
    assert set(report['producers'])==set(report['tables'])
    publish=json.loads((Path(spec['work'])/'candidate-publish.json').read_text())
    assert publish['producers']==report['producers']
    model=json.loads((Path(spec['work'])/'candidate-model.json').read_text())
    records={name:json.loads(Path(pin['path']).read_text()) for name,pin in report['producers'].items()}
    assert all(r['job']==selective.PRODUCER_JOB and r['commit']==head_commit and r['recorded']=='with production' for r in records.values())
    from congress_api.lake import captures as lake_captures,filenames
    from viewer_publication import producer_proof
    versions_at=producer_proof.versions_at
    def dirty_filename_version(commit,**kwargs):
        value=dict(versions_at(commit,**kwargs))
        if commit==head_commit:value['filename_readings']=filenames.current_version()
        return value
    monkeypatch.setattr(producer_proof,'versions_at',dirty_filename_version)
    assert snapshot_reasons(model,records,mapping_current=lake_captures.current_version())==[]


def test_an_unclean_tree_writes_no_producer_record_and_says_so(tmp_path,fixture,monkeypatch):
    import viewer_publication.archive_selective as selective
    monkeypatch.setattr(selective,'_writer',lambda run:None)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    report=execute(spec)
    assert report['producers']=={'unavailable':'the checkout was not clean, so no commit can be named'}
    assert 'producers' not in json.loads((Path(spec['work'])/'candidate-publish.json').read_text())


def test_records_written_on_a_resume_of_an_older_build_say_so(tmp_path,fixture,monkeypatch):
    """spec-run's case: tables built before producer records existed, recorded on resume."""
    import subprocess as sp
    import viewer_publication.archive_selective as selective
    head_commit=sp.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    monkeypatch.setattr(selective,'_writer',lambda run:None)  # first run: no clean identity, no records
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0)
    assert 'unavailable' in execute(spec)['producers']
    monkeypatch.setattr(selective,'_writer',lambda run:dict(job=selective.PRODUCER_JOB,commit=head_commit,lockfile_digest='0'*64))
    report=execute(dict(spec,resume=True))
    records=[json.loads(Path(pin['path']).read_text()) for pin in report['producers'].values()]
    assert records and all(r['recorded']=='after production, on resume' for r in records)


def test_historical_record_only_replay_preserves_rows_but_refuses_head_producer_proof(tmp_path, monkeypatch):
    from hashlib import sha256

    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_backfill_job import load_spec, plan
    from viewer_publication.archive_record_backfill import MEETING_DOCUMENT_REFERENCES, MEETING_PRIOR
    from viewer_publication.archive_selective_records import SELECTION_SCHEMA
    from viewer_publication.producer_proof import BACKFILL, snapshot_reasons

    # Rehearse the historical endpoint; attributing these versions to today's HEAD must refuse.
    assert meeting_records.current_versions() != MEETING_DOCUMENT_REFERENCES
    monkeypatch.setattr(meeting_records, "current_versions", lambda: dict(MEETING_DOCUMENT_REFERENCES))

    def pin(path):
        return dict(path=str(path), **file_pin(path))

    mirror = tmp_path/'mirror'
    mirror.mkdir()
    raw = tmp_path/'raw'
    raw.mkdir()
    inline = json.dumps({'committeeMeeting': {'eventId': '100031', 'chamber': 'House',
        'meetingDocuments': [{'url': 'https://example.test/one.pdf', 'documentType': 'Support Document'}]}}).encode()
    receipt = mirror/'meeting.jsonl'
    receipt.write_bytes(inline+b'\n')
    held = meeting_records.build_meeting_record_row(sha256(inline).hexdigest(), 'congress_gov', inline,
        parser_version=MEETING_PRIOR['congress_gov'])
    house = dict(record_sha='aa'*32, source='house_xml', parser_version=MEETING_PRIOR['house_xml'],
        status='completed', error_type=None, meetings=[])
    old_meetings = meeting_records.table([house, held])
    nested = old_meetings.schema.field('meetings').type.value_type
    fields = pa.struct([field for field in nested if field.name!='document_references'])
    meetings_schema = old_meetings.schema.set(old_meetings.schema.get_field_index('meetings'),
        pa.field('meetings', pa.list_(pa.field('element', fields, nullable=False)), nullable=False))
    meeting_path = tmp_path/'meetings.parquet'
    pq.write_table(pa.Table.from_pylist(old_meetings.to_pylist(), schema=meetings_schema), meeting_path)
    selection = tmp_path/'selection.parquet'
    pq.write_table(pa.Table.from_pylist([dict(receipt_key=receipt.name, receipt_line=1, source_url='')],
        schema=SELECTION_SCHEMA), selection)

    prior = dict(appearance_records.current_versions(), mods='older-mods', senate_page='older-senate')
    bodies = {'mods': b'<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Hearing</title></titleInfo></mods>',
              'senate_page': b'<html><body><h1>Hearing</h1></body></html>'}
    appearances = []
    for source, version in prior.items():
        if source in bodies:
            body = bodies[source]
            digest = sha256(body).hexdigest()
            dest = mirror/'bodies'/'sha256'/digest[:2]/digest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        else:
            digest = sha256(source.encode()).hexdigest()
        appearances.append(dict(record_sha=digest, source=source, parser_version=version,
            status='completed', appearances=[]))
    appearance_path = tmp_path/'appearances.parquet'
    pq.write_table(appearance_records.table(appearances), appearance_path)

    bases = dict(meeting_records=pin(meeting_path), appearance_records=pin(appearance_path))
    model = tmp_path/'model.json'
    model.write_text(json.dumps(dict(**{name:dict(kind='parquet', **item) for name,item in bases.items()},
        parser_versions=dict(meeting_records=MEETING_PRIOR, appearance_records=prior), unreadable_files=[])))
    work = tmp_path/'work'
    spec_path = tmp_path/'record-only.json'
    spec_path.write_text(json.dumps(dict(version=1, work=str(work), engine_config=os.environ['DOCSPEC_JOB_CONFIG'],
        record_only=dict(base_model=pin(model), bases=bases, raw_root=str(raw), raw_mirror=str(mirror),
            max_work_items=2, meeting_selection=pin(selection), replay_sources=['mods', 'senate_page']))))
    spec = load_spec(spec_path)
    assert plan(spec)['executed'] is False and not work.exists()
    result = execute(spec)['tables']
    assert {name:(item['reused_rows'],item['appended']) for name,item in result.items()} == {
        'meeting_records': (1,1), 'appearance_records': (4,2)}
    current_meetings = pq.read_table(result['meeting_records']['selector']['path']).to_pylist()
    assert {row['source']: row['parser_version'] for row in current_meetings} == MEETING_DOCUMENT_REFERENCES
    assert next(r for r in current_meetings if r['source']=='congress_gov')['meetings'][0]['document_references'] == [
        dict(collection='meetingDocuments',ordinal=0,url='https://example.test/one.pdf',role='Support Document',
             format=None,description=None,name=None)]
    current_appearances = pq.read_table(result['appearance_records']['selector']['path']).to_pylist()
    assert all(row in current_appearances for row in appearance_records.table(appearances).to_pylist())
    records = {name:json.loads(Path(item['producer']['path']).read_text()) for name,item in result.items()}
    assert all(r['job']==BACKFILL for r in records.values())
    selected = {name:item['selector'] for name,item in result.items()}
    # Gate 5 reads real checked-in code in a separate process, outside this historical simulation.
    # Real current-code acceptance remains covered in test_producer_proof.py.
    producing_commit = records['meeting_records']['commit']
    assert snapshot_reasons(dict(**selected,parser_versions=dict(meeting_records=MEETING_DOCUMENT_REFERENCES,
        appearance_records=appearance_records.current_versions())),records) == [
            f'producer proof: meeting_records: the code at {producing_commit[:12]} computes another version than the pinned rows carry'
        ]


@pytest.mark.parametrize('endpoint,source', [
    ('prior', 'house_xml'), ('prior', 'congress_gov'),
    ('current', 'house_xml'), ('current', 'congress_gov'),
])
def test_record_only_meeting_transition_refuses_unreviewed_versions_before_base_read(endpoint, source, monkeypatch):
    from viewer_publication import archive_record_backfill as backfill

    prior = dict(backfill.MEETING_PRIOR)
    current = dict(backfill.MEETING_DOCUMENT_REFERENCES)
    (prior if endpoint == 'prior' else current)[source] = '0' * 64
    monkeypatch.setattr(meeting_records, 'current_versions', lambda: current)
    def reject_base(*args, **kwargs):
        pytest.fail('An unreviewed transition reached the base reader')
    monkeypatch.setattr(backfill, '_base_keys', reject_base)
    with pytest.raises(ValueError, match='reviewed document-reference transition'):
        backfill._meetings(None, prior, None)


def test_record_only_appearances_replay_exactly_the_sources_whose_version_moved(monkeypatch):
    from viewer_publication import archive_record_backfill as backfill

    current = dict(congress_gov='c1', house_xml='h1', senate_page='s1', mods='m2')
    assert backfill._moved_sources(current, dict(current, mods='m1'), ['mods']) == {'mods'}
    assert backfill._moved_sources(current, dict(current, mods='m1', senate_page='s0'),
                                   ['senate_page', 'mods']) == {'mods', 'senate_page'}
    with pytest.raises(ValueError, match='name different sources: youtube'):
        backfill._moved_sources(current, dict(current, mods='m1', youtube='y1'), ['mods'])
    with pytest.raises(ValueError, match='name different sources: house_xml'):
        backfill._moved_sources(current, {k: v for k, v in current.items() if k != 'house_xml'}, ['mods'])
    # The move must be exactly the reviewed one, in both directions.
    with pytest.raises(ValueError, match=r"moved sources \['mods', 'senate_page'\] differ from the reviewed replay_sources \['mods'\]"):
        backfill._moved_sources(current, dict(current, mods='m1', senate_page='s0'), ['mods'])
    with pytest.raises(ValueError, match=r"moved sources \['mods'\] differ"):
        backfill._moved_sources(current, dict(current, mods='m1'), ['mods', 'senate_page'])
    # Congress.gov rows are built from inline receipt lines, which a stored-body replay cannot read.
    with pytest.raises(ValueError, match='cannot replay inline-built sources: congress_gov'):
        backfill._moved_sources(current, dict(current, congress_gov='c0'), ['congress_gov'])
    # Refused before any base row is examined (the caller has already loaded the base file):
    # nothing moved, an unreviewed move, an inline source.
    monkeypatch.setattr(backfill, '_base_keys', lambda *a, **k: pytest.fail('a refused replay examined the base rows'))
    monkeypatch.setattr(appearance_records, 'current_versions', lambda: dict(current))
    for prior, reviewed, refusal in ((dict(current), ['mods'], 'no source producer version moved'),
                                     (dict(current, mods='m1'), ['senate_page'], 'differ from the reviewed'),
                                     (dict(current, congress_gov='c0'), ['congress_gov'], 'inline-built')):
        with pytest.raises(ValueError, match=refusal):
            backfill._appearances(None, prior, reviewed, directory=None)


def test_record_only_mods_move_replays_mods_and_promotes_older_rows_to_the_new_columns(tmp_path):
    """The lake's older table lacks committees/committee_members: its rows come through verbatim with them null."""
    from hashlib import sha256

    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_backfill_job import load_spec

    def pin(path):
        return dict(path=str(path), **file_pin(path))

    mirror, raw = tmp_path/'mirror', tmp_path/'raw'
    raw.mkdir()
    current = appearance_records.current_versions()
    prior = dict(current, mods='older-mods')
    body = (b'<mods xmlns="http://www.loc.gov/mods/v3"><titleInfo><title>Hearing</title></titleInfo>'
            b'<extension><congCommittee authorityId="SSAP00" chamber="S" congress="114" type="S">'
            b'<name type="authority-standard">Senate Appropriations</name></congCommittee></extension></mods>')
    mods_sha = sha256(body).hexdigest()
    dest = mirror/'bodies'/'sha256'/mods_sha[:2]/mods_sha
    dest.parent.mkdir(parents=True)
    dest.write_bytes(body)
    rows = [dict(record_sha=mods_sha if source == 'mods' else sha256(source.encode()).hexdigest(), source=source,
                 parser_version=version, status='completed', appearances=[]) for source, version in prior.items()]
    base_table = appearance_records.table(rows).drop_columns(['committees', 'committee_members'])
    base = tmp_path/'appearances.parquet'
    pq.write_table(base_table, base)
    model = tmp_path/'model.json'
    model.write_text(json.dumps(dict(appearance_records=dict(kind='parquet', **pin(base)),
        parser_versions=dict(appearance_records=prior), unreadable_files=[])))
    spec_path = tmp_path/'record-only.json'
    job = dict(base_model=pin(model), bases=dict(appearance_records=pin(base)), raw_root=str(raw),
               raw_mirror=str(mirror), max_work_items=1)
    spec = dict(version=1, work=str(tmp_path/'work'), engine_config=os.environ['DOCSPEC_JOB_CONFIG'], record_only=job)
    # The reviewed move is part of the spec: an appearance replay without it is refused at load.
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match='reviewed replay_sources'):
        load_spec(spec_path)
    spec_path.write_text(json.dumps(dict(spec, record_only=dict(job, replay_sources=['mods']))))
    result = execute(load_spec(spec_path))['tables']['appearance_records']
    assert (result['reused_rows'], result['appended'], result['replayed_sources']) == (4, 1, ['mods'])
    out = pq.read_table(result['selector']['path'])
    assert out.schema.names == appearance_records.ARROW_SCHEMA.names
    by_key = {(r['record_sha'].hex(), r['parser_version']): r for r in out.to_pylist()}
    assert len(by_key) == 5
    for row in base_table.to_pylist():
        assert by_key[(row['record_sha'].hex(), row['parser_version'])] == dict(row, committees=None, committee_members=None)
    replayed = by_key[(mods_sha, current['mods'])]
    assert (replayed['status'], replayed['committees']) == ('completed', ['ssap00'])
    proof = json.loads(Path(result['producer']['path']).read_text())
    assert (proof['reused_rows'], proof['appended'], proof['replayed_sources']) == (4, 1, ['mods'])


def test_record_only_retained_committee_checks_custody_and_returns_only_append_rows(tmp_path):
    import gzip
    from hashlib import sha256

    from congress_api.lake import committee_records
    from congress_api.retention.provenance import file_pin
    from viewer_publication.archive_backfill_job import load_spec
    from viewer_publication.archive_record_backfill import HOUSE_XML_PATH, _retained_committee_selection
    from viewer_publication.producer_proof import BACKFILL, IMPORT, record, snapshot_reasons

    def pin(path):
        return dict(path=str(path), **file_pin(path))

    body = b'''<committee-meeting meeting-id="HMKP118438">
    <meeting-documents><meeting-document type="CA"><filename-metadata><amdt-num>7</amdt-num></filename-metadata>
    <files><file doc-url="https://docs.house.gov/meetings/IF/IF00/20250625/118438/amendment.pdf"/></files>
    </meeting-document></meeting-documents></committee-meeting>'''
    digest = sha256(body).hexdigest()
    body_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    stored = tmp_path/'mirror'/body_key
    stored.parent.mkdir(parents=True)
    stored.write_bytes(gzip.compress(body,mtime=0))
    receipt_key = 'receipts/house/meeting-xml/undated/fixture.jsonl.gz'
    receipt = tmp_path/'raw'/receipt_key
    receipt.parent.mkdir(parents=True)
    selection = tmp_path/'selection.json'

    def inputs(event, *, line=2, source_digest=digest, verified=True):
        path = f'{HOUSE_XML_PATH}{event}.xml'
        reference = dict(status='verified' if verified else 'missing', reference_kind='retained-file',
            fidelity='retained-file', resolution='digest_verified', family='house/meeting-xml',
            original_path=path, source_file=path, sha256=digest, source_sha256=digest, body_key=body_key)
        retained = dict(captures=[], source_file=path, record=dict(original_path=path), file_references=[reference])
        receipt.write_bytes(gzip.compress(('{}\n'+json.dumps(retained)+'\n').encode(),mtime=0))
        selection.write_text(json.dumps([dict(receipt_line=line, event_id=event,
            original_path=path, record_sha=source_digest)]))

    inputs('118438', line=3)
    with pytest.raises(ValueError, match='missing receipt lines'):
        _retained_committee_selection(selection, receipt, 1)
    inputs('118438', verified=False)
    with pytest.raises(ValueError, match='does not verify'):
        _retained_committee_selection(selection, receipt, 1)
    inputs('118438', source_digest='a'*64)
    with pytest.raises(ValueError, match='does not verify'):
        _retained_committee_selection(selection, receipt, 1)
    inputs('118438')
    version = committee_records.current_versions()
    old = tmp_path/'retained.parquet'
    pq.write_table(committee_records.table([committee_records.build_row('a'*64, committee_records.SOURCE,
        body,parser_version=version[committee_records.SOURCE])]),old)
    old_pin = pin(old)
    model = tmp_path/'model.json'
    base_selector = dict(kind='native_table', metadata_location='fixture/metadata.json',
                         table_uuid='fixture-table', snapshot=6186, schema_id=0)
    model.write_text(json.dumps(dict(committee_records=base_selector,
        parser_versions=dict(committee_records=version), unreadable_files=[])))
    path = tmp_path/'job.json'

    def spec(work, key=receipt_key):
        path.write_text(json.dumps(dict(version=1, work=str(tmp_path/work),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],record_only=dict(base_model=pin(model),bases={},
                raw_root=str(tmp_path/'raw'),raw_mirror=str(tmp_path/'mirror'),max_work_items=1,
                retained_committee=dict(receipt_key=key,receipt=pin(receipt),selection=pin(selection),base=old_pin)))))
        return load_spec(path)

    with pytest.raises(ValueError, match='path does not match its key'):
        spec('wrong-key', 'receipts/house/meeting-xml/undated/another.jsonl.gz')
    inputs('118455')  # The path and verified digest are internally consistent, but the body names 118438.
    with pytest.raises(ValueError, match='does not contain records for its selected event'):
        execute(spec('wrong-event'))
    inputs('118438')
    item = execute(spec('append'))['tables']['committee_records']
    [row] = pq.read_table(item['selector']['path']).to_pylist()
    assert row['record_sha'].hex() == digest and row['event_id'] == '118438'
    assert row['records'][0]['number'] == '7' and row['records'][0]['bill'] is None
    assert item['delta_only'] and item['appended'] == item['existing_rows_checked'] == 1
    proof = json.loads(Path(item['producer']['path']).read_text())
    assert proof['final_reconciliation_required'] and 'base_selector' not in proof
    assert pin(old) == old_pin

    base_origin = tmp_path/'base-origin.json'
    origin = record(base_origin, input='committee_records', selector=dict(kind='parquet', **old_pin), job=BACKFILL)
    base_producer = tmp_path/'base-import.json'
    imported = record(base_producer, input='committee_records', selector=base_selector, job=IMPORT)
    imported.update(source=old_pin, verified='EXCEPT ALL both ways against the source file',
                    origin=dict(pin=pin(base_origin), record=origin))
    base_producer.write_text(json.dumps(imported))

    def composition(work, **changes):
        inputs = dict(base=old_pin, base_producer=pin(base_producer),
                      delta=pin(Path(item['selector']['path'])), delta_producer=item['producer'],
                      expected_base_rows=1, expected_delta_rows=1)
        path.write_text(json.dumps(dict(version=1, work=str(tmp_path/work),
            engine_config=os.environ['DOCSPEC_JOB_CONFIG'],record_only=dict(base_model=pin(model),bases={},
                raw_root=str(tmp_path/'unavailable-raw'),raw_mirror=str(tmp_path/'unavailable-mirror'),
                max_work_items=1, committee_composition=dict(inputs, **changes)))))
        return load_spec(path)

    with pytest.raises(ValueError, match='the producer record names another selector'):
        execute(composition('wrong-delta', delta=old_pin))
    duplicate_proof = tmp_path/'duplicate-delta.json'
    duplicate_proof.write_text(json.dumps(dict(proof, selector=dict(kind='parquet', **old_pin))))
    with pytest.raises(ValueError, match='primary keys overlap'):
        execute(composition('overlap', delta=old_pin, delta_producer=pin(duplicate_proof)))

    result = execute(composition('compose'))['tables']['committee_records']
    combined = pq.read_table(result['selector']['path'])
    assert combined.num_rows == 2
    assert combined.slice(0, 1).equals(pq.read_table(old))
    assert combined.slice(1, 1).equals(pq.read_table(item['selector']['path']))
    assert result['reused_rows'] == result['appended'] == 1
    combined_proof = json.loads(Path(result['producer']['path']).read_text())
    assert combined_proof['job'] == BACKFILL and 'delta_only' not in combined_proof
    assert snapshot_reasons(dict(committee_records=result['selector'], parser_versions=dict(committee_records=version)),
                            {'committee_records': combined_proof}) == []
