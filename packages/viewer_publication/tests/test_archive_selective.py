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


def test_the_job_owns_model_output_while_a_pinned_spicy_regs_is_accepted(tmp_path,fixture):
    # Contract: the selective job owns work/model-{output,scratch} (db7345c8); spicy-regs is a pin (925036be).
    from viewer_publication.archive_backfill_job import load_spec
    spec=selective_spec(tmp_path,fixture,dict(captures=B))
    pinned=spec['selective']['model']['spicy_regs']
    assert set(pinned)=={'path','sha256','size'} and Path(pinned['path']).is_file()
    path=tmp_path/'spec.json';value=json.loads(path.read_text())
    value['selective']['model']['output']=str(tmp_path/'caller-output');path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='the job owns work/model'):load_spec(path)
    assert not (tmp_path/'work').exists()


def test_refuses_a_digest_mismatch_and_absent_raw_root_before_any_effect(tmp_path,fixture):
    spec=selective_spec(tmp_path/'digest',fixture,dict(captures=B))
    spec['selective']['base']['captures']['sha256']='0'*64
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not Path(spec['work']).exists()
    moved=dict(fixture,raw=tmp_path/'absent')
    with pytest.raises(ValueError,match='raw_root is absent'):selective_spec(tmp_path/'raw',moved,dict(captures=B))


def test_a_pinned_input_manifest_must_match_before_any_effect(tmp_path,fixture):
    manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    from congress_api.retention.provenance import file_pin
    spec=selective_spec(tmp_path,fixture,dict(captures=B))
    spec['selective']['input_manifest']=dict(path=str(manifest),**file_pin(manifest))
    manifest.write_text('{"changed":true}')
    with pytest.raises(ValueError,match='does not match its pin'):execute(spec)
    assert not Path(spec['work']).exists()


def test_zero_hits_stops_before_any_table_exists(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures="receipt_key='absent'"))
    with pytest.raises(SelectiveStop,match='selects no rows'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_stale_unselected_record_rows_stop_before_any_table(tmp_path,fixture):
    # Defect guarded: re-stamping them with the current version, an unverified claim.
    def stale(rows):rows[0]['parser_version']='old'
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(meeting_records=changed(tmp_path,fixture,'meeting_records',stale)))
    with pytest.raises(SelectiveStop,match='D3/D4 have no compatible versions'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_readings_at_an_uncovered_version_stop_before_any_table(tmp_path,fixture):
    def stale(rows):rows[0]['parser_version']='old'
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(readings=changed(tmp_path,fixture,'readings',stale)))
    with pytest.raises(SelectiveStop,match='neither current nor in the compatible-versions registry'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_a_duplicate_base_primary_key_stops_before_any_table(tmp_path,fixture):
    def duplicate(rows):rows.append(dict(rows[0]))
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,
        base=dict(readings=changed(tmp_path,fixture,'readings',duplicate)))
    with pytest.raises(ValueError,match='duplicated before selection'):execute(spec)
    assert not Path(spec['catalog_root']).exists()


def test_covered_readings_are_copied_verbatim_at_their_old_versions(tmp_path,fixture,monkeypatch):
    from congress_api.lake import compatible_versions as cv
    pins=cv.current_pins()
    def relabel(rows):
        for row in rows:row['parser_version']='old-'+row['parser']
    registry=tmp_path/'registry.json'
    registry.write_text(json.dumps(dict(version=2,entries=[compatible_entry(p,'old-'+p,pins[p]) for p in cv.LEAF_PARSERS])))
    monkeypatch.setattr(cv,'REGISTRY',registry)
    base=changed(tmp_path,fixture,'readings',relabel)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(readings=base),through='tables')
    report=execute(spec)
    assert report['status']=='tables_built' and not (Path(spec['work'])/'candidate-model.json').exists()
    assert sorted_rows(head(spec,'readings'))==sorted_rows(pq.read_table(base).to_pylist())


def test_a_base_that_predates_a_nullable_column_seeds_null_and_reports_it_added(tmp_path,fixture):
    # Defect guarded: seeding and diffing every current schema column against a base written
    # before the column existed (v21 captures before mapping_version/original_path).
    table=pq.read_table(fixture['base']['captures']);old=tmp_path/'old-captures.parquet'
    pq.write_table(table.drop(['h_content_disposition']),old)
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(captures=str(old)),through='tables')
    report=execute(spec)
    assert report['status']=='tables_built' and report['rebuilt_diff'].get('added_columns')==['h_content_disposition']
    rows=head(spec,'captures')
    assert all(row['h_content_disposition'] is None for row in rows if not row['receipt_key'].endswith('/b.jsonl.gz'))
    assert len(rows)==table.num_rows


def test_an_all_selected_table_seeds_nothing_without_reading_its_shape(tmp_path,fixture):
    table=pq.read_table(fixture['base']['captures']);old=tmp_path/'old-captures.parquet'
    pq.write_table(table.drop(['receipt_line_bytes'] if 'receipt_line_bytes' in table.column_names else ['h_content_disposition']),old)
    spec=selective_spec(tmp_path,fixture,dict(captures='true'),differential_rows=0,base=dict(captures=str(old)),through='tables')
    report=execute(spec)
    assert report['tables']['captures']['reused']==0 and report['tables']['captures']['selected']==table.num_rows


def test_d2_reads_missing_readings_from_the_local_mirror(tmp_path,fixture):
    # Defect guarded: _daily wrote an empty body inventory, so any D2 work stayed pending and
    # the run stopped "Daily producers stopped at pending". Existing cases had no D2 work.
    base=pq.read_table(fixture['base']['readings']).to_pylist()
    body=next(row['body_sha'] for row in base if row['parser']!='sniff')
    def missing(rows):rows[:]=[row for row in rows if row['body_sha']!=body]
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,base=dict(readings=changed(tmp_path,fixture,'readings',missing)),
        through='tables')
    assert execute(spec)['status']=='tables_built'
    reread={(row['parser'],row['status']) for row in head(spec,'readings') if row['body_sha']==body}
    assert reread=={(row['parser'],row['status']) for row in base if row['body_sha']==body}


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


def test_selected_records_recompute_and_unselected_are_copied_verbatim(tmp_path,fixture):
    meeting=meeting_records.current_versions()
    spec=selective_spec(tmp_path,fixture,dict(meeting_records="source='house_xml'",appearance_records="source='congress_gov'",filename_readings="filename LIKE 'b-one%'"))
    report=execute(spec)
    assert report['tables']['meeting_records']['appended']==report['tables']['meeting_records']['selected']>0
    assert {row['parser_version'] for row in head(spec,'meeting_records')}<=set(meeting.values())
    assert {row['catalog_version'] for row in head(spec,'filename_readings')}=={catalog_version()}
    for name in ('meeting_records','appearance_records','filename_readings'):
        assert sorted_rows(head(spec,name))==sorted_rows(pq.read_table(fixture['base'][name]).to_pylist())
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


def test_a_model_runtime_change_resumes_and_a_predicate_change_still_refuses(tmp_path,fixture):
    spec=selective_spec(tmp_path,fixture,dict(captures=B),differential_rows=0,through='tables')
    assert execute(spec)['status']=='tables_built'
    # Defect guarded: identity covering the model runtime, so a retry with a new pool redoes D1-D4.
    other=tmp_path/'model-runtime.json';other.write_text(Path(os.environ['DOCSPEC_JOB_CONFIG']).read_text())
    retry=dict(spec,resume=True,through='model',selective=dict(spec['selective'],model=dict(spec['selective']['model'],engine_config=str(other))))
    assert execute(retry)['status']=='built'
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
    state_path=Path(spec['work'])/'state.json';state=json.loads(state_path.read_text());state.pop('producers');state_path.write_text(json.dumps(state))
    monkeypatch.setattr(selective,'_writer',lambda run:dict(job=selective.PRODUCER_JOB,commit=head_commit,lockfile_digest='0'*64))
    report=execute(dict(spec,resume=True))
    records=[json.loads(Path(pin['path']).read_text()) for pin in report['producers'].values()]
    assert records and all(r['recorded']=='after production, on resume' for r in records)
