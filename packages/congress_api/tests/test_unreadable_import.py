"""Unreadable decisions survive deleting every local producer stage."""
import hashlib
import gzip
import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.retention.body_store import BodyStore, LocalAdapter, RawNameCollision
from congress_api.retention import provenance
from test_filename_readings import input_tables, engine, reader, Worker, TerminalWorker, STAMP


def decision():
    return dict(id='a'*64,record_sha='b'*64,parser='filename',parser_version='c'*64,
        reason='timeout',decided_by='filename_readings',decided_at=STAMP,supersedes=None)


def test_import_qualifies_exact_bytes_and_uses_create_only_store(tmp_path):
    source=tmp_path/'decisions.jsonl'; payload=(json.dumps(decision())+'\n').encode()
    source.write_bytes(payload)
    raw=tmp_path/'raw'; store=BodyStore(LocalAdapter(raw))
    result=provenance.import_unreadable(store,source,decided_at=STAMP)
    expected='provenance/unreadable/'+provenance.timestamp_key(STAMP)+'-'+hashlib.sha256(payload).hexdigest()+'.jsonl'
    assert result['key']==expected and result['records']==1
    assert (raw/expected).read_bytes()==payload
    with pytest.raises(RawNameCollision):
        provenance.import_unreadable(store,source,decided_at=STAMP)
    assert (raw/expected).read_bytes()==payload


def test_invalid_decisions_refuse_before_storage(tmp_path):
    class Never:
        def put(self,*args,**kwargs):raise AssertionError('storage before validation')
    path=tmp_path/'bad.jsonl'; path.write_text('{}\n')
    with pytest.raises(ValueError):provenance.import_unreadable(Never(),path,decided_at=STAMP)


def test_raw_only_rebuild_excludes_unreadable_and_retries_unavailable(tmp_path):
    raw=tmp_path/'raw'; store=BodyStore(LocalAdapter(raw))
    bad=dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',url='https://a.test/Bad.pdf')
    pending=dict(receipt_key='r',receipt_line=2,capture_index=0,mode='fetch',url='https://a.test/Later.pdf')
    from congress_api.lake.captures import stage_captures
    def retain_receipt(row):
        key='receipts/documents/2026-10-27/'+str(row['receipt_line'])+'.jsonl.gz'
        record=dict(run_id='fixture',mode='fetch',outcome='failed',family='documents',
            requested_url=row['url'],url=row['url'],retrieved_at=STAMP,http_status=500,captures=[])
        payload=gzip.compress((json.dumps(record)+'\n').encode(),mtime=0)
        source=tmp_path/('source-'+str(row['receipt_line']));source.write_bytes(payload)
        store.put(key,source,'application/x-ndjson');source.unlink()
        authority=tmp_path/('qualified-'+str(row['receipt_line'])+'.json')
        authority.write_text(json.dumps(dict(path=str((raw/key).resolve()),size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),producer='fixture creation')))
        return dict(key=key,path=str(raw/key),qualification=str(authority))
    raw_bad=retain_receipt(bad);raw_pending=retain_receipt(pending)
    def rebuild(files,name):
        return stage_captures(files,engine=engine(),work=tmp_path/name)/'captures.parquet'
    captures=rebuild([raw_bad],'old-captures')
    staged=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'old-stage',
        worker_factory=TerminalWorker,decided_at=STAMP,unreadable_store=store)
    assert staged['unreadable_pending'] is False and staged['unreadable_key']
    assert (raw/staged['unreadable_key']).is_file()
    class Unavailable(Worker):
        def parse(self,*args):raise OSError('input unavailable')
    captures=rebuild([raw_pending],'pending-captures')
    with pytest.raises(OSError,match='unavailable'):
        reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'unavailable-stage',
            worker_factory=Unavailable,decided_at=STAMP,unreadable_store=store)
    inventory=[dict(key=str(path.relative_to(raw)),path=str(path)) for path in raw.rglob('*.jsonl')]
    assert len(inventory)==1
    for name in ('old-stage','unavailable-stage','old-captures','pending-captures'):
        shutil.rmtree(tmp_path/name)
    captures=rebuild([raw_bad,raw_pending],'rebuilt-captures')
    rebuilt=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'rebuilt',
        worker_factory=Worker,decided_at=STAMP,unreadable_files=inventory,unreadable_store=store)
    assert pq.read_table(rebuilt['work_list'])['filename'].to_pylist()==['Later.pdf']
    assert pq.read_table(rebuilt['readings'])['filename'].to_pylist()==['Later.pdf']
    newer=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'new-version',
        worker_factory=Worker,decided_at=STAMP,unreadable_files=inventory,unreadable_store=store,
        vocabularies={'member_surnames':{'119':['New']}})
    assert pq.read_metadata(newer['work_list']).num_rows==2


def test_stage_only_pending_decisions_refuse_append_before_catalog_effect(tmp_path):
    captures=input_tables(tmp_path,[dict(receipt_key='r',receipt_line=1,capture_index=0,mode='fetch',url='https://a.test/Bad.pdf')])
    staged=reader().stage(captures=captures,recovery_files=[],engine=engine(),work=tmp_path/'stage',
        worker_factory=TerminalWorker,decided_at=STAMP)
    assert staged['unreadable_pending'] is True
    assert (Path(staged['unreadable_stage'])/'manifest.json').is_file()
    with pytest.raises(ValueError,match='unreadable.*import'):
        reader().append(staged,engine=object(),work=tmp_path/'append',catalog_root=tmp_path/'catalog',
            table={'namespace':['archive'],'name':'filename_readings'})
    assert not (tmp_path/'catalog').exists() and not (tmp_path/'append').exists()
    result=provenance.apply_staged(staged['unreadable_stage'],BodyStore(LocalAdapter(tmp_path/'raw')))
    assert result['records']==1
    assert (tmp_path/'raw'/staged['unreadable_key']).is_file()


@pytest.mark.parametrize('identity', ['body_sha256', 'record_sha'])
def test_shared_import_accepts_body_or_record_identity(tmp_path,identity):
    row=decision();row[identity]=row.pop('record_sha')
    path=tmp_path/'decisions.jsonl';path.write_text(json.dumps(row)+'\n')
    result=provenance.import_unreadable(BodyStore(LocalAdapter(tmp_path/'raw')),path,decided_at=STAMP)
    assert result['records']==1


def test_import_failure_does_not_claim_durability(tmp_path):
    class Refused:
        def put(self,*args,**kwargs):raise OSError('raw unavailable')
    path=tmp_path/'decisions.jsonl';path.write_text(json.dumps(decision())+'\n')
    with pytest.raises(OSError,match='raw unavailable'):
        provenance.import_unreadable(Refused(),path,decided_at=STAMP)


def test_content_key_and_uploaded_bytes_share_one_frozen_source(tmp_path):
    path=tmp_path/'decisions.jsonl';payload=(json.dumps(decision())+'\n').encode();path.write_bytes(payload)
    class ReplacedSource:
        def put(self,key,frozen,media):
            path.write_text('{}\n')
            assert Path(frozen).read_bytes()==payload
            assert key.endswith(hashlib.sha256(payload).hexdigest()+'.jsonl')
    result=provenance.import_unreadable(ReplacedSource(),path,decided_at=STAMP)
    assert result['sha256']==hashlib.sha256(payload).hexdigest()



def test_reviewed_import_refuses_source_replacement_before_create(tmp_path):
    import sys
    stage=tmp_path/'stage';stage.mkdir()
    path=tmp_path/'records.jsonl';path.write_text(json.dumps(decision())+'\n')
    imported=provenance.import_unreadable(BodyStore(LocalAdapter(stage)),path,decided_at=STAMP)
    provenance.finish_stage(stage,kind='unreadable',provenance=imported['key'],records=1,
        inputs={},extra=dict(decided_at=STAMP))
    reviewed=stage/imported['key']; changed=dict(decision(),reason='parser_crash')
    class Never:
        def put(self,*args,**kwargs):raise AssertionError('unreviewed bytes reached storage')
    def replace_on_import(frame,event,arg):
        if event=='call' and frame.f_code is provenance.import_unreadable.__code__:
            reviewed.write_text(json.dumps(changed)+'\n')
    previous=sys.getprofile();sys.setprofile(replace_on_import)
    try:
        with pytest.raises(ValueError,match='changed'):
            provenance.apply_staged(stage,Never())
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize('rows', [
    [dict(decision(),record_sha='B'*64)],
    [decision(),dict(decision(),record_sha='d'*64)],
])
def test_noncanonical_identity_and_duplicate_ids_refuse_before_create(tmp_path,rows):
    class Never:
        def put(self,*args,**kwargs):raise AssertionError('invalid decisions reached storage')
    path=tmp_path/'bad.jsonl';path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    with pytest.raises(ValueError):provenance.import_unreadable(Never(),path,decided_at=STAMP)
