"""Stored-digest repairs require measured bytes; weekly facts are incremental."""
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from test_raw_verifier import Store, inputs, key, engine
from congress_api.retention.raw_verifier import verify
from congress_api.retention.raw_repair import prepare_repair
from congress_api.retention.provenance import file_pin

STAMP='2026-10-27T00:00:00Z'
LOCATOR='receipts/f/2026-10-27/run.jsonl.gz'


def population(tmp_path,count=1,*,candidate=0,assertion=None,previous=(),old_equals=False):
    originals=[f'measured-verification-{i}'.encode() for i in range(count)]
    values={key(data):(gzip.compress(data,mtime=0),None) for data in originals}
    physical=list(values)[candidate]; stored=values[physical][0]
    actual=hashlib.sha256(stored).hexdigest()
    asserted=actual if assertion is None else assertion
    rows=[dict(body_key=k,stored_bytes=len(v[0]),stored_sha256=(asserted if old_equals and k==physical else '0'*64),
        receipt_key=LOCATOR,receipt_line=1,pointer_json='["content","body"]') for k,v in values.items()]
    receipt=dict(captures=[dict(body_key=physical,stored_bytes=len(stored),stored_sha256=asserted)])
    captures,receipts,history=inputs(tmp_path,rows,receipts=[receipt],previous=previous)
    # B12 requires original immutable observation positions.
    table=pq.read_table(captures);table=table.append_column('_capture_order',pa.array(range(count),type=pa.int64()))
    pq.write_table(table,captures)
    return Store(values),captures,receipts,history,physical,actual


def run(tmp_path,case,*,name='job',seed='fixed',stamp=STAMP):
    store,captures,receipts,previous,*_=case
    return verify(store,captures=captures,receipts=receipts,previous=previous,
        engine=engine(),work=tmp_path/name,checked_at=stamp,seed=seed)


@pytest.mark.parametrize('old_equals',[False,True])
def test_measured_receipt_contradiction_refuses_even_without_index_change(tmp_path,old_equals):
    case=population(tmp_path,assertion='f'*64,old_equals=old_equals)
    before=file_pin(case[1]);report=run(tmp_path,case)
    assert not report['valid'] and report['digest_conflicts']==1 and report['digest_repairs']==0
    assert report['accepted_records']==0 and report['candidate_records']==1
    [conflict]=pq.read_table(tmp_path/'job/digest-conflicts.parquet').to_pylist()
    assert conflict['key']==case[4] and conflict['receipt_key']==LOCATOR
    assert conflict['receipt_stored_sha256']=='f'*64 and conflict['measured_stored_sha256']==case[5]
    assert not Path(report['records']).exists() and file_pin(case[1])==before


def test_actual_verified_repair_file_passes_ingress_and_preserves_facts(tmp_path):
    case=population(tmp_path);report=run(tmp_path,case)
    assert report['valid'] and report['digest_repairs']==1
    repairs=tmp_path/'job/digest-repairs.parquet';[row]=pq.read_table(repairs).to_pylist()
    assert row['stored_sha256']==row['measured_stored_sha256']==row['receipt_stored_sha256']==case[5]
    assert row['stored_bytes']==row['size'] and row['sha256_verified'] is True
    assert row['evidence_source']=='current_read'
    stage=prepare_repair(case[1],repairs,engine=engine(),work=tmp_path/'repair',expected=file_pin(case[1])['sha256'])
    old=pq.read_table(case[1]).to_pylist();new=pq.read_table(stage['output']).to_pylist()
    assert new==[dict(old[0],stored_sha256=case[5])]


def test_failed_measured_read_cannot_qualify_a_repair(tmp_path):
    case=population(tmp_path)
    class Changed(Store):
        def get(self,k):
            response=super().get(k);response['ETag']='changed-during-read';return response
    changed=Changed(case[0].values);case=(changed,*case[1:])
    report=run(tmp_path,case)
    assert not report['valid'] and report['content_errors']==1 and report['digest_repairs']==0


def outside_sample(values,seed='fixed'):
    ordered=sorted(values,key=lambda k:(hashlib.sha256((seed+k).encode()).digest(),k))
    return ordered[-1]


def test_unsampled_receipt_assertion_is_explicitly_unmeasured_without_extra_get(tmp_path):
    initial=population(tmp_path,30)
    outside=outside_sample(initial[0].values)
    candidate=list(initial[0].values).index(outside)
    case=population(tmp_path,30,candidate=candidate)
    report=run(tmp_path,case)
    assert report['valid'] and report['unmeasured_candidates']==1 and report['digest_repairs']==0
    assert len(case[0].reads)==len(set(case[0].reads))==25 and outside not in case[0].reads
    assert case[0].list_calls==1
    [row]=pq.read_table(tmp_path/'job/unmeasured-digests.parquet').to_pylist()
    assert row['key']==outside and row['status']=='unmeasured'


@pytest.mark.parametrize('flag,digest,repairs',[(True,'actual',1),(True,None,0),(False,'actual',0)])
def test_prior_whole_read_digest_requires_all_matching_evidence(tmp_path,flag,digest,repairs):
    initial=population(tmp_path,30);outside=outside_sample(initial[0].values)
    stored=initial[0].values[outside][0];actual=hashlib.sha256(stored).hexdigest()
    previous=[dict(key=outside,size=len(stored),etag=hashlib.md5(stored).hexdigest(),
        sha256_verified=flag,stored_sha256=actual if digest=='actual' else digest,
        checked_at='2026-10-26T00:00:00Z',job='prior')]
    case=population(tmp_path,30,candidate=list(initial[0].values).index(outside),previous=previous)
    report=run(tmp_path,case)
    assert report['valid'] and report['digest_repairs']==repairs
    assert report['unmeasured_candidates']==1-repairs and outside not in case[0].reads
    if repairs:
        [row]=pq.read_table(tmp_path/'job/digest-repairs.parquet').to_pylist()
        assert row['evidence_source']=='prior_verification' and row['stored_sha256']==actual


def test_prior_and_fresh_measured_digest_disagreement_is_not_a_winner_choice(tmp_path):
    case=population(tmp_path);stored=case[0].values[case[4]][0]
    prior=[dict(key=case[4],size=len(stored),etag=hashlib.md5(stored).hexdigest(),
        sha256_verified=True,stored_sha256='f'*64,checked_at='2026-10-26T00:00:00Z',job='prior')]
    case=population(tmp_path,previous=prior);report=run(tmp_path,case)
    assert not report['valid'] and report['digest_conflicts']==1 and report['digest_repairs']==0


def test_weekly_history_appends_only_new_baseline_and_fresh_sample(tmp_path):
    case=population(tmp_path,30);first=run(tmp_path,case,name='first')
    records=[json.loads(line) for line in Path(first['records']).read_text().splitlines()]
    assert len(records)==30 and sum(row['sha256_verified'] for row in records)==25
    assert all(bool(row['stored_sha256'])==row['sha256_verified'] for row in records)
    history=tmp_path/'history.jsonl.gz'
    with gzip.open(history,'wt') as out:
        for row in records:out.write(json.dumps(row)+'\n')
    previous=[dict(key='provenance/verification/history.jsonl',path=str(history))]
    for week in (1,2):
        report=verify(Store(case[0].values),captures=case[1],receipts=case[2],previous=previous,
            engine=engine(),work=tmp_path/f'week-{week}',checked_at=f'2026-10-{27+week:02d}T00:00:00Z',seed='fixed')
        fresh=[json.loads(line) for line in Path(report['records']).read_text().splitlines()]
        assert report['valid'] and report['accepted_records']==len(fresh)==25
        assert {r['key'] for r in fresh}==set(case[0].reads)
        records+=fresh
        with gzip.open(history,'wt') as out:
            for row in records:out.write(json.dumps(row)+'\n')


def test_empty_verified_delta_is_pinned_checked_noop(tmp_path):
    from congress_api.cli.raw_verify import apply_staged
    captures,receipts,previous=inputs(tmp_path,[])
    report=verify(Store({}),captures=captures,receipts=receipts,previous=previous,engine=engine(),
        work=tmp_path/'job',checked_at=STAMP,seed='fixed')
    assert report['valid'] and report['accepted_records']==0
    class NoPut:
        def put(self,*args):raise AssertionError('empty raw provenance write')
    assert apply_staged(tmp_path/'job',NoPut())['provenance'] is None
    Path(report['records']).write_text('{}\n')
    with pytest.raises(ValueError,match='changed'):apply_staged(tmp_path/'job',NoPut())


@pytest.mark.parametrize('change',[
    'missing','unverified','measured_digest','receipt_digest','measured_size','asserted_size','bad_digest',
])
def test_repair_ingress_refuses_unqualified_or_inconsistent_measurement(tmp_path,change):
    from test_raw_repair import fixture
    captures,repairs,_=fixture(tmp_path)
    [row]=pq.read_table(repairs).to_pylist()
    if change=='missing':row.pop('measured_stored_sha256')
    elif change=='unverified':row['sha256_verified']=False
    elif change=='measured_digest':row['measured_stored_sha256']='f'*64
    elif change=='receipt_digest':row['receipt_stored_sha256']='f'*64
    elif change=='measured_size':row['size']+=1
    elif change=='asserted_size':row['receipt_stored_bytes']+=1
    else:row['stored_sha256']='not-a-digest'
    pq.write_table(pa.Table.from_pylist([row]),repairs)
    with pytest.raises(ValueError,match='[Mm]easured|[Aa]mbiguous'):
        prepare_repair(captures,repairs,engine=engine(),work=tmp_path/'repair',expected=file_pin(captures)['sha256'])
    assert not (tmp_path/'repair/manifest.json').exists()


def test_native_receipt_concat_and_materialized_consumers_are_reused(tmp_path):
    from congress_api.retention.provenance import run_job
    case=population(tmp_path)
    receipts=[dict(captures=None,file_references=[]),dict(captures=[],file_references=None),
        dict(captures=[{},{}],file_references=[{},{}]),
        dict(captures=[{}],file_references=None),dict(captures=None,file_references=[{}]),
        dict(captures=[None],file_references=[None])]
    with gzip.open(case[2][0]['path'],'wt') as out:
        for row in receipts:out.write(json.dumps(row)+'\n')
    run(tmp_path,case)
    job=json.loads((tmp_path/'job/inventory/job.json').read_text())
    definitions={s['name']:s for s in job['steps']}
    assert all(definitions[name]['materialize'] for name in ('listed','index_refs','receipt_refs','verified','compared'))
    before=[]
    for step in job['steps']:
        before.append(dict(step,materialize=False))
        if step['name']=='receipt_refs':break
    probe=tmp_path/'producer';probe.mkdir()
    result=run_job(probe,engine(),inputs=job['inputs'],steps=before,outputs=[],queries=[
        dict(name='plan',sql='EXPLAIN SELECT * FROM receipt_refs'),
        dict(name='count',sql='SELECT count(*) AS n FROM receipt_refs')])
    physical=next(row['plan'] for row in result['plan'] if row['plan_type']=='physical_plan')
    (probe/'physical.txt').write_text(physical)
    assert physical.count('UnnestExec')==1
    assert physical.count('StreamingTableExec')==1
    assert result['count'][0]['n']==8
    downstream=tmp_path/'consumer';downstream.mkdir()
    result=run_job(downstream,engine(),inputs=job['inputs'],steps=job['steps'],outputs=[dict(item,path=str(downstream/Path(item['path']).name)) for item in job['outputs']],
        queries=[dict(name=name,sql='EXPLAIN SELECT * FROM '+name) for name in ('compared','orphans','work','digest_evidence')])
    for name,rows in result.items():
        physical=next(row['plan'] for row in rows if row['plan_type']=='physical_plan')
        (downstream/(name+'-physical.txt')).write_text(physical)
        assert 'UnnestExec' not in physical and 'WindowAggExec' not in physical,(name,physical)
        assert '__raw_line' not in physical
    execution=json.loads((tmp_path/'job/inventory/result.json').read_text())
    assert {s['name'] for s in execution['steps'] if s['storage']!='view'}>=set(('listed','index_refs','receipt_refs','verified','compared'))
    final=json.loads((tmp_path/'job/final/job.json').read_text())
    assert {i['name'] for i in final['inputs']}=={'baseline','digest_evidence','checked'}


def test_new_unsampled_body_is_one_delta_and_new_sample_upgrades_old_baseline(tmp_path):
    case=population(tmp_path,30);first=run(tmp_path,case,name='first')
    history=tmp_path/'history.jsonl.gz'
    prior=[json.loads(line) for line in Path(first['records']).read_text().splitlines()]
    with gzip.open(history,'wt') as out:
        for row in prior:out.write(json.dumps(row)+'\n')
    values=dict(case[0].values)
    for n in range(100):
        original=f'new-unsampled-{n}'.encode();newkey=key(original)
        candidate=dict(values,**{newkey:(gzip.compress(original,mtime=0),None)})
        if outside_sample(candidate)==newkey:break
    else:raise AssertionError('fixture needs an unsampled new body')
    values=candidate
    rows=pq.read_table(case[1]).to_pylist();rows.append(dict(rows[0],body_key=newkey,
        stored_bytes=len(values[newkey][0]),_capture_order=len(rows)))
    pq.write_table(pa.Table.from_pylist(rows),case[1])
    report=verify(Store(values),captures=case[1],receipts=case[2],
        previous=[dict(key='provenance/verification/history.jsonl',path=str(history))],
        engine=engine(),work=tmp_path/'second',checked_at='2026-10-28T00:00:00Z',seed='fixed')
    delta=[json.loads(line) for line in Path(report['records']).read_text().splitlines()]
    assert report['valid'] and report['accepted_records']==len(delta)==26
    [new]=[row for row in delta if row['key']==newkey]
    assert new['sha256_verified'] is False and new['stored_sha256'] is None
    prior_false={row['key'] for row in prior if not row['sha256_verified']}
    seed=next('week'+str(n) for n in range(100) if any(k in sorted(values,key=lambda k:hashlib.sha256(('week'+str(n)+k).encode()).digest())[:25] for k in prior_false))
    report=verify(Store(values),captures=case[1],receipts=case[2],
        previous=[dict(key='provenance/verification/history.jsonl',path=str(history))],
        engine=engine(),work=tmp_path/'upgrade',checked_at='2026-10-29T00:00:00Z',seed=seed)
    delta=[json.loads(line) for line in Path(report['records']).read_text().splitlines()]
    assert report['valid'] and any(row['key'] in prior_false and row['sha256_verified'] and row['stored_sha256'] for row in delta)


def test_drifted_prior_measurement_does_not_authorize_unsampled_repair(tmp_path):
    initial=population(tmp_path,30);outside=outside_sample(initial[0].values)
    stored=initial[0].values[outside][0]
    previous=[dict(key=outside,size=len(stored),etag='different-listed-object',sha256_verified=True,
        stored_sha256=hashlib.sha256(stored).hexdigest(),checked_at='2026-10-26T00:00:00Z',job='prior')]
    case=population(tmp_path,30,candidate=list(initial[0].values).index(outside),previous=previous)
    report=run(tmp_path,case)
    assert not report['valid'] and report['mismatches']==1 and report['digest_repairs']==0
    assert outside not in case[0].reads and not Path(report['records']).exists()



def reviewed_delta(work):
    work.mkdir()
    records=work/'verification.jsonl'
    payload=(json.dumps(dict(key='bodies/sha256/'+'a'*2+'/'+'a'*64,size=1,etag='x',
        sha256_verified=True,stored_sha256='b'*64,checked_at=STAMP,job='raw-verifier'))+'\n').encode()
    records.write_bytes(payload)
    (work/'report.json').write_text(json.dumps(dict(valid=True,accepted_records=1,
        records_sha256=hashlib.sha256(payload).hexdigest(),provenance_key='provenance/verification/pinned.jsonl',
        listed=1,checked=1)))
    return records,payload


def test_verification_apply_refuses_changed_source_before_frozen_copy_create(tmp_path):
    import sys
    from congress_api.cli.raw_verify import apply_staged
    from congress_shared.custody import copy_checked
    records,_=reviewed_delta(tmp_path/'job')
    class NoPut:
        def put(self,*args,**kwargs):raise AssertionError('unreviewed records reached storage')
    def change_before_copy(frame,event,arg):
        if event=='call' and frame.f_code is copy_checked.__code__:
            records.write_text('{"different":"valid JSON"}\n')
    previous=sys.getprofile();sys.setprofile(change_before_copy)
    try:
        with pytest.raises(ValueError,match='changed'):
            apply_staged(tmp_path/'job',NoPut())
    finally:sys.setprofile(previous)


def test_verification_apply_uses_reviewed_frozen_bytes_after_source_replacement(tmp_path):
    import sys
    from congress_api.cli.raw_verify import apply_staged
    from congress_api.retention.body_store import BodyStore,LocalAdapter
    records,payload=reviewed_delta(tmp_path/'job');raw=tmp_path/'raw'
    def change_original_at_upload(frame,event,arg):
        if event=='call' and frame.f_code is BodyStore.put.__code__:
            records.write_text('{"different":"valid JSON"}\n')
    previous=sys.getprofile();sys.setprofile(change_original_at_upload)
    try:result=apply_staged(tmp_path/'job',BodyStore(LocalAdapter(raw)))
    finally:sys.setprofile(previous)
    assert (raw/result['provenance']).read_bytes()==payload
